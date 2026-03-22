"""
Knowledge Base — Upload, chunk, embed, and retrieve documents for autopilot context.

Pipeline: Upload → Parse → Chunk (500 tokens) → Embed (OpenAI) → Store (pgvector)
Retrieval: Embed topic → Cosine similarity search → Top-K chunks → Inject in prompt
"""
import base64
import logging
from io import BytesIO

import requests as http_requests
import tiktoken
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import KnowledgeBaseDocument, KnowledgeBaseChunk
from .repurpose import is_safe_url, extract_article_content

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_TEXT_LENGTH = 100_000  # ~25K tokens


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(content_b64: str) -> str:
    """Extract text from a base64-encoded PDF."""
    from PyPDF2 import PdfReader
    raw = base64.b64decode(content_b64)
    if len(raw) > MAX_FILE_SIZE:
        raise ValueError("Fichier trop volumineux (max 5 MB)")
    reader = PdfReader(BytesIO(raw))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _extract_text_from_docx(content_b64: str) -> str:
    """Extract text from a base64-encoded DOCX."""
    from docx import Document
    raw = base64.b64decode(content_b64)
    if len(raw) > MAX_FILE_SIZE:
        raise ValueError("Fichier trop volumineux (max 5 MB)")
    doc = Document(BytesIO(raw))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_text_from_url(url: str) -> str:
    """Fetch URL and extract article text."""
    if not is_safe_url(url):
        raise ValueError("URL non autorisée")
    resp = http_requests.get(
        url,
        timeout=15,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; PostFlow/1.0)'},
    )
    resp.raise_for_status()
    return extract_article_content(resp.text)


def extract_text(source_type: str, content: str = "", url: str = "") -> str:
    """Extract text based on source type. Returns cleaned text."""
    if source_type == 'pdf':
        text = _extract_text_from_pdf(content)
    elif source_type == 'docx':
        text = _extract_text_from_docx(content)
    elif source_type == 'url':
        text = _extract_text_from_url(url)
    elif source_type in ('txt', 'paste'):
        if content.startswith('data:'):
            # Handle base64 data URI for txt files
            _, encoded = content.split(',', 1) if ',' in content else ('', content)
            text = base64.b64decode(encoded).decode('utf-8', errors='replace')
        else:
            text = content
    else:
        raise ValueError(f"Type de source non supporté: {source_type}")

    text = text.strip()
    if not text:
        raise ValueError("Aucun texte extrait du document")
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
    return text


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, max_tokens: int = 500, overlap: int = 50) -> list[str]:
    """Split text into chunks of ~max_tokens with overlap."""
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = start + max_tokens
        chunk_tokens = tokens[start:end]
        chunk_text_str = enc.decode(chunk_tokens)
        if chunk_text_str.strip():
            chunks.append(chunk_text_str.strip())
        start = end - overlap if end < len(tokens) else len(tokens)
    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts using OpenAI text-embedding-3-small (1536 dims)."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]


# ---------------------------------------------------------------------------
# Document processing pipeline
# ---------------------------------------------------------------------------

def process_document(document: KnowledgeBaseDocument):
    """Parse, chunk, embed, and store a document. Updates document status."""
    try:
        text = document.raw_text
        if not text.strip():
            document.status = 'error'
            document.error_message = 'Aucun texte extrait'
            document.save(update_fields=['status', 'error_message'])
            return

        # Chunk
        chunks = chunk_text(text)
        if not chunks:
            document.status = 'error'
            document.error_message = 'Impossible de découper le texte en chunks'
            document.save(update_fields=['status', 'error_message'])
            return

        # Embed all chunks in one batch
        embeddings = embed_texts(chunks)

        # Bulk create chunks
        KnowledgeBaseChunk.objects.bulk_create([
            KnowledgeBaseChunk(
                document=document,
                user=document.user,
                content=chunk,
                chunk_index=i,
                embedding=embedding,
            )
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ])

        document.chunk_count = len(chunks)
        document.status = 'ready'
        document.save(update_fields=['chunk_count', 'status'])
        logger.info(f"KB: processed '{document.title}' → {len(chunks)} chunks for {document.user.username}")

    except Exception as e:
        logger.error(f"KB processing failed for doc {document.id}: {e}", exc_info=True)
        document.status = 'error'
        document.error_message = str(e)[:500]
        document.save(update_fields=['status', 'error_message'])


# ---------------------------------------------------------------------------
# Retrieval (used by autopilot)
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_relevant_chunks(user, topic: str, top_k: int = 5) -> str:
    """Embed the topic, find closest chunks via cosine similarity, return formatted context."""
    chunks_qs = KnowledgeBaseChunk.objects.filter(
        user=user, document__status='ready'
    ).select_related('document')

    if not chunks_qs.exists():
        return ""

    try:
        # Embed the query
        query_embedding = embed_texts([topic])[0]

        # Compute similarity for each chunk in Python
        scored = []
        for chunk in chunks_qs:
            if not chunk.embedding:
                continue
            sim = _cosine_similarity(query_embedding, chunk.embedding)
            scored.append((sim, chunk))

        # Sort by similarity (highest first) and take top_k
        scored.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored[:top_k]

        if not top_chunks:
            return ""

        lines = [
            "CONNAISSANCES DE L'AUTEUR (extraits de sa base de connaissances personnelle) :",
            "Utilise ces informations pour enrichir le contenu avec l'expertise unique de l'auteur :",
        ]
        for _sim, chunk in top_chunks:
            doc_title = chunk.document.title
            lines.append(f"\n--- [{doc_title}] ---")
            lines.append(chunk.content)

        context = "\n".join(lines)
        if len(context) > 3000:
            context = context[:3000] + "\n..."

        logger.info(f"KB: retrieved {len(top_chunks)} chunks for topic '{topic[:50]}' (user: {user.username})")
        return context

    except Exception as e:
        logger.warning(f"KB retrieval failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

def _serialize_document(doc: KnowledgeBaseDocument) -> dict:
    return {
        'id': doc.id,
        'title': doc.title,
        'source_type': doc.source_type,
        'source_url': doc.source_url,
        'chunk_count': doc.chunk_count,
        'status': doc.status,
        'error_message': doc.error_message,
        'created_at': doc.created_at.isoformat(),
    }


def _get_kb_limit(user) -> int:
    """Get max KB documents for the user's plan."""
    from .llm import get_user_plan
    plan = get_user_plan(user)
    plan_limits = settings.PLAN_LIMITS.get(plan, settings.PLAN_LIMITS['free'])
    return plan_limits.get('kb_max_documents', 5)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_documents(request):
    """List user's knowledge base documents."""
    docs = KnowledgeBaseDocument.objects.filter(user=request.user)
    return Response([_serialize_document(d) for d in docs])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_document(request):
    """Upload a document to the knowledge base."""
    data = request.data
    title = (data.get('title') or '').strip()
    source_type = data.get('source_type', '')
    content = data.get('content', '')
    url = data.get('url', '')

    if not title:
        return Response({'error': 'Le titre est requis'}, status=status.HTTP_400_BAD_REQUEST)

    if source_type not in ('pdf', 'txt', 'docx', 'url', 'paste'):
        return Response({'error': 'Type de source invalide'}, status=status.HTTP_400_BAD_REQUEST)

    if source_type == 'url' and not url:
        return Response({'error': "L'URL est requise"}, status=status.HTTP_400_BAD_REQUEST)

    if source_type in ('pdf', 'txt', 'docx', 'paste') and not content:
        return Response({'error': 'Le contenu est requis'}, status=status.HTTP_400_BAD_REQUEST)

    # Check plan limit
    current_count = KnowledgeBaseDocument.objects.filter(user=request.user).count()
    max_docs = _get_kb_limit(request.user)
    if current_count >= max_docs:
        return Response(
            {'error': f'Limite atteinte ({max_docs} documents max pour votre plan)'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Extract text
    try:
        raw_text = extract_text(source_type, content=content, url=url)
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"KB text extraction failed: {e}", exc_info=True)
        return Response({'error': 'Erreur lors de l\'extraction du texte'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Create document
    doc = KnowledgeBaseDocument.objects.create(
        user=request.user,
        title=title[:300],
        source_type=source_type,
        source_url=url[:500] if source_type == 'url' else '',
        raw_text=raw_text,
        status='processing',
    )

    # Process (chunk + embed) — synchronous, takes 2-5 seconds
    process_document(doc)

    return Response(_serialize_document(doc), status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_document(request, pk):
    """Delete a knowledge base document and all its chunks."""
    try:
        doc = KnowledgeBaseDocument.objects.get(pk=pk, user=request.user)
    except KnowledgeBaseDocument.DoesNotExist:
        return Response({'error': 'Document introuvable'}, status=status.HTTP_404_NOT_FOUND)

    doc.delete()  # CASCADE deletes chunks
    return Response({'ok': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def kb_stats(request):
    """Get knowledge base statistics."""
    docs = KnowledgeBaseDocument.objects.filter(user=request.user)
    total_docs = docs.count()
    ready_docs = docs.filter(status='ready').count()
    total_chunks = KnowledgeBaseChunk.objects.filter(user=request.user).count()
    max_docs = _get_kb_limit(request.user)

    return Response({
        'total_documents': total_docs,
        'ready_documents': ready_docs,
        'total_chunks': total_chunks,
        'max_documents': max_docs,
    })

"""Markdown-aware chunker for RAG memory.

Strategy: split on top-level markdown headings (#, ##) so each chunk preserves
semantic boundaries. Within a section, if the body exceeds the per-chunk cap,
fall back to paragraph-window splitting with overlap so context spans aren't
broken mid-thought.

Returns a list of ``(title, body)`` tuples. ``title`` is the nearest heading
above the chunk (or ``""`` for body-only chunks); it's used as the
``Memory.title`` field and contributes to retrieval relevance ("Voix de marque"
is itself a useful semantic signal).

Sizes are configurable via settings:

  * ``RAG_CHUNK_SIZE_TOKENS`` — target chunk size (default 250 tokens ≈ 1000 chars)
  * ``RAG_CHUNK_OVERLAP`` — overlap between adjacent chunks (default 25 tokens
    ≈ 100 chars). Lets long sections preserve context across splits.

We measure in characters internally (cheap, no tokenizer dep) and approximate
4 chars ≈ 1 token for both EN and FR. If you serve heavily non-Latin content
where that ratio breaks down, plug a real tokenizer into ``estimate_tokens``.
"""
from __future__ import annotations

import re

from django.conf import settings


# Chars-per-token approximation — keep in sync with embeddings.estimate_tokens.
_CHARS_PER_TOKEN = 4


def _target_chars() -> int:
    tokens = int(getattr(settings, "RAG_CHUNK_SIZE_TOKENS", 250))
    return tokens * _CHARS_PER_TOKEN


def _max_chars() -> int:
    # Hard ceiling = 1.5× target. Beyond that we force a split.
    return int(_target_chars() * 1.5)


def _overlap_chars() -> int:
    tokens = int(getattr(settings, "RAG_CHUNK_OVERLAP", 25))
    return tokens * _CHARS_PER_TOKEN


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, preserving non-empty paragraphs."""
    parts = re.split(r"\n\s*\n", text or "")
    return [p.strip() for p in parts if p.strip()]


def _chunk_body(body: str, max_chars: int) -> list[str]:
    """Split a heading-less body into windowed chunks under ``max_chars``.

    Greedy paragraph packing: keep concatenating until we'd exceed the cap,
    then start a fresh chunk seeded with overlap from the previous one.
    """
    paragraphs = _split_paragraphs(body)
    if not paragraphs:
        return []
    overlap = _overlap_chars()
    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        # If a single paragraph blows the cap, hard-split it on sentences.
        if len(p) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", p)
            buf = ""
            for s in sentences:
                if len(buf) + len(s) + 1 > max_chars and buf:
                    chunks.append(buf.strip())
                    buf = s
                else:
                    buf = (buf + " " + s).strip() if buf else s
            if buf:
                current = buf
            continue
        # Normal case: pack greedily.
        candidate = (current + "\n\n" + p).strip() if current else p
        if len(candidate) > max_chars and current:
            chunks.append(current.strip())
            # Seed next chunk with tail overlap to keep context flowing.
            tail = current[-overlap:] if overlap else ""
            current = (tail + "\n\n" + p).strip() if tail else p
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return chunks


def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """Return list of ``(title, chunk_body)`` preserving heading context.

    - ``# Title`` and ``## Subtitle`` mark section boundaries.
    - Each section larger than the per-chunk cap is split into multiple
      windowed chunks, all keeping the same ``title``.
    - Pre-first-heading content (intro paragraphs) gets ``title=""``.
    - H3+ headings stay inside their parent section (we don't recurse — going
      deeper makes chunks too small to be useful for retrieval).
    """
    if not text or not text.strip():
        return []
    max_chars = _max_chars()

    sections: list[tuple[str, str]] = []
    lines = text.splitlines()
    current_title = ""
    current_buf: list[str] = []
    heading_re = re.compile(r"^(#{1,2})\s+(.+?)\s*$")

    def flush() -> None:
        body = "\n".join(current_buf).strip()
        if body:
            sections.append((current_title, body))

    for line in lines:
        m = heading_re.match(line)
        if m:
            flush()
            current_title = m.group(2).strip()
            current_buf = []
        else:
            current_buf.append(line)
    flush()

    # Expand sections too big for one chunk.
    out: list[tuple[str, str]] = []
    for title, body in sections:
        if len(body) <= max_chars:
            out.append((title, body))
            continue
        for piece in _chunk_body(body, max_chars=max_chars):
            out.append((title, piece))
    return out


def chunk_text(text: str) -> list[tuple[str, str]]:
    """Plain-text variant (no heading parsing). All chunks have ``title=""``."""
    if not text or not text.strip():
        return []
    pieces = _chunk_body(text, max_chars=_max_chars())
    return [("", piece) for piece in pieces]

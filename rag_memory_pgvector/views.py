"""API views — index / retrieve / feedback.

All three default to ``IsAuthenticated`` because RAG memory is private to a
tenant — exposing retrieve to anonymous traffic is almost never what you
want. The tenant resolution is pluggable via ``get_tenant()`` below: by
default it returns ``request.user``, which matches the default
``RAG_TENANT_MODEL = settings.AUTH_USER_MODEL``. Override the view (or set
``RAG_TENANT_RESOLVER = "myproj.rag.get_tenant"``) when your tenant model
isn't the user.
"""
from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .selectors import retrieve_top_k
from .serializers import (
    FeedbackRequestSerializer,
    FeedbackResponseSerializer,
    IndexRequestSerializer,
    IndexResponseSerializer,
    RetrievedChunkSerializer,
    RetrieveRequestSerializer,
    RetrieveResponseSerializer,
)
from .services import index_text, mark_used


def _default_get_tenant(request: Request):
    """Default tenant resolver — uses the authenticated user.

    Match this to your ``RAG_TENANT_MODEL`` setting. If you set
    ``RAG_TENANT_MODEL = "sites.Site"``, you must provide a custom resolver
    via ``RAG_TENANT_RESOLVER`` that returns a ``Site`` instance — e.g. one
    parsed from a ``?site=<id>`` query param or a subdomain header.
    """
    return request.user


def get_tenant(request: Request):
    path = getattr(settings, "RAG_TENANT_RESOLVER", None)
    resolver = import_string(path) if path else _default_get_tenant
    return resolver(request)


class IndexView(APIView):
    """POST /api/rag/index/ — chunk + embed + upsert a source."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = IndexRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = index_text(
            tenant=get_tenant(request),
            kind=ser.validated_data["kind"],
            content=ser.validated_data["content"],
            title=ser.validated_data.get("title", ""),
            source_ref=ser.validated_data.get("source_ref", ""),
            metadata=ser.validated_data.get("metadata", {}),
            chunker=ser.validated_data.get("chunker", "markdown"),
        )
        # On provider failure (e.g. VOYAGE_API_KEY missing) services.index_text
        # returns {"error": ...} with created=reused=0 — surface as 503.
        if result.get("error") and not result.get("created"):
            return Response(
                IndexResponseSerializer(result).data,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(IndexResponseSerializer(result).data)


class RetrieveView(APIView):
    """POST /api/rag/retrieve/ — top-k semantic search."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = RetrieveRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        results = retrieve_top_k(
            tenant=get_tenant(request),
            query=ser.validated_data["query"],
            k=ser.validated_data.get("k"),
            kinds=ser.validated_data.get("kinds"),
        )
        resp = RetrieveResponseSerializer({
            "results": RetrievedChunkSerializer(results, many=True).data,
        })
        return Response(resp.data)


class FeedbackView(APIView):
    """POST /api/rag/feedback/ — bump feedback_score on a batch of chunks."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = FeedbackRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        updated = mark_used(
            memory_ids=ser.validated_data["memory_ids"],
            rating=ser.validated_data["rating"],
        )
        return Response(FeedbackResponseSerializer({"updated": updated}).data)

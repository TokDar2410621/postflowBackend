"""
API endpoints for server-side PDF export via Playwright.
"""
import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.http import HttpResponse
from django.conf import settings

from .pdf_export import generate_pdf

logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def export_carousel_pdf(request):
    """Generate a pixel-perfect carousel PDF via Playwright screenshots."""
    data = request.data
    slides = data.get("slides", [])
    theme = data.get("theme", {})
    linkedin_profile = data.get("linkedInProfile")
    text_scale = data.get("textScale", 1)
    topic = data.get("topic", "")

    if not slides:
        return HttpResponse(
            '{"error": "Aucune slide fournie"}',
            content_type="application/json",
            status=400,
        )

    # Build per-slide render data
    slides_data = []
    for i, slide in enumerate(slides):
        slides_data.append({
            "format": "carousel",
            "slide": slide,
            "theme": theme,
            "index": i,
            "total": len(slides),
            "linkedInProfile": linkedin_profile,
            "textScale": text_scale,
        })

    try:
        frontend_url = settings.FRONTEND_URL
        pdf_bytes = generate_pdf(slides_data, frontend_url)
    except Exception as e:
        logger.exception("Carousel PDF generation failed")
        return HttpResponse(
            f'{{"error": "Erreur generation PDF: {str(e)}"}}',
            content_type="application/json",
            status=500,
        )

    safe_topic = (
        topic[:30]
        .replace(" ", "-")
        .encode("ascii", "ignore")
        .decode()
        or "postflow"
    )
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="carousel-{safe_topic}.pdf"'
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def export_cartoon_pdf(request):
    """Generate a pixel-perfect cartoon dialogue PDF via Playwright screenshots."""
    data = request.data
    panels = data.get("panels", [])
    characters = data.get("characters", {})
    theme = data.get("theme", {})
    text_scale = data.get("textScale", 1)
    topic = data.get("topic", "")

    if not panels:
        return HttpResponse(
            '{"error": "Aucun panel fourni"}',
            content_type="application/json",
            status=400,
        )

    # Build per-panel render data
    slides_data = []
    for i, panel in enumerate(panels):
        slides_data.append({
            "format": "cartoon",
            "panel": panel,
            "panelIndex": i,
            "totalPanels": len(panels),
            "mainCharacter": characters.get("main", {}),
            "otherCharacter": characters.get("other", {}),
            "theme": theme,
            "textScale": text_scale,
        })

    try:
        frontend_url = settings.FRONTEND_URL
        pdf_bytes = generate_pdf(slides_data, frontend_url)
    except Exception as e:
        logger.exception("Cartoon PDF generation failed")
        return HttpResponse(
            f'{{"error": "Erreur generation PDF: {str(e)}"}}',
            content_type="application/json",
            status=500,
        )

    safe_topic = (
        topic[:30]
        .replace(" ", "-")
        .encode("ascii", "ignore")
        .decode()
        or "postflow"
    )
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="cartoon-{safe_topic}.pdf"'
    return response

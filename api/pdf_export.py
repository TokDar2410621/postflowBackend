"""
Server-side PDF generation using Playwright (headless Chromium).
Screenshots each slide at 1080x1080 via the frontend /render page,
then assembles them into a multi-page PDF with Pillow.
"""
import json
import threading
import logging
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)

_pw_instance = None
_browser = None
_lock = threading.Lock()


def _get_browser():
    """Lazy singleton: one Chromium instance per gunicorn worker."""
    global _pw_instance, _browser
    with _lock:
        if _browser is None or not _browser.is_connected():
            from playwright.sync_api import sync_playwright
            _pw_instance = sync_playwright().start()
            _browser = _pw_instance.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            logger.info("Playwright browser launched")
        return _browser


def generate_pdf(slides_data: list, frontend_url: str) -> bytes:
    """
    Render each slide via the frontend /render page and screenshot it.

    slides_data: list of dicts, each containing the props for
                 SlidePreview (format='carousel') or CartoonDialoguePanel (format='cartoon').
    frontend_url: base URL of the frontend (e.g. https://smart-post-assistant.vercel.app)

    Returns: bytes of the assembled PDF.
    """
    browser = _get_browser()
    context = browser.new_context(
        viewport={"width": 1080, "height": 1080},
        device_scale_factor=2,
    )
    page = context.new_page()

    try:
        # Load the render page once
        render_url = frontend_url.rstrip("/") + "/render"
        page.goto(render_url, wait_until="networkidle", timeout=30000)

        screenshots = []
        for i, slide_data in enumerate(slides_data):
            gen = i + 1
            # Inject data and trigger React render
            page.evaluate(
                "data => window.__renderSlide(data)",
                slide_data,
            )
            # Wait for React to render with the correct generation
            page.wait_for_selector(
                f'[data-generation="{gen}"]',
                timeout=10000,
            )
            # Small pause for CSS transitions/paint
            page.wait_for_timeout(150)

            # Screenshot the slide container
            element = page.locator("#slide-container")
            png_bytes = element.screenshot(type="png")
            screenshots.append(png_bytes)

        return _assemble_pdf(screenshots)

    finally:
        context.close()


def _assemble_pdf(screenshots: list) -> bytes:
    """Combine PNG screenshots into a multi-page PDF using Pillow."""
    images = []
    for s in screenshots:
        img = Image.open(BytesIO(s))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        images.append(img)

    if not images:
        raise ValueError("No screenshots to assemble")

    buf = BytesIO()
    images[0].save(
        buf,
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=150,
    )
    buf.seek(0)
    return buf.read()

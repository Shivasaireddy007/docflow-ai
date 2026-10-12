"""File type detection and page rendering.

The type comes from the file's own bytes, never from the upload's Content-Type or extension.
"""

import io

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
WEBP = "image/webp"

# Models read receipts fine at this size, and smaller images are much faster to process.
MAX_SIDE_PX = 1600
PDF_RENDER_SCALE = 2.0  # 144 dpi


class UnsupportedFile(Exception):
    pass


def sniff(data: bytes) -> str | None:
    """The file's real type from its first bytes, or None if it isn't a supported type."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    return None


def page_count(data: bytes, content_type: str) -> int:
    """Pages in the file; raises UnsupportedFile if it can't be opened."""
    if content_type != PDF:
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise UnsupportedFile("The image is damaged or not really an image.") from exc
        return 1
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise UnsupportedFile("The PDF is damaged or password-protected.") from exc
    try:
        return len(pdf)
    finally:
        pdf.close()


def _png(image: Image.Image) -> bytes:
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def to_pages(data: bytes, content_type: str, max_pages: int) -> list[bytes]:
    """Each page as a PNG, scaled so its longest side is at most MAX_SIDE_PX."""
    if content_type != PDF:
        with Image.open(io.BytesIO(data)) as image:
            return [_png(image)]
    pdf = pdfium.PdfDocument(data)
    try:
        return [_png(pdf[i].render(scale=PDF_RENDER_SCALE).to_pil()) for i in range(min(len(pdf), max_pages))]
    finally:
        pdf.close()

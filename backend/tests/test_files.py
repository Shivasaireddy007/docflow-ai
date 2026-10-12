import io

import pytest
from PIL import Image

from pipeline import files
from tests.conftest import image_bytes, pdf_bytes


def test_types_come_from_the_bytes() -> None:
    assert files.sniff(image_bytes(fmt="PNG")) == files.PNG
    assert files.sniff(image_bytes(fmt="JPEG")) == files.JPEG
    assert files.sniff(image_bytes(fmt="WEBP")) == files.WEBP
    assert files.sniff(pdf_bytes(1)) == files.PDF
    assert files.sniff(b"<html>") is None


def test_pdf_pages_are_rendered_and_capped() -> None:
    pages = files.to_pages(pdf_bytes(5), files.PDF, max_pages=3)

    assert len(pages) == 3
    assert all(files.sniff(page) == files.PNG for page in pages)


def test_large_images_are_scaled_down_for_the_model() -> None:
    [page] = files.to_pages(image_bytes(size=(3000, 4000)), files.PNG, max_pages=10)

    with Image.open(io.BytesIO(page)) as image:
        assert max(image.size) == files.MAX_SIDE_PX


def test_damaged_files_are_rejected() -> None:
    with pytest.raises(files.UnsupportedFile):
        files.page_count(b"%PDF-1.7 broken", files.PDF)
    with pytest.raises(files.UnsupportedFile):
        files.page_count(b"\x89PNG\r\n\x1a\nbroken", files.PNG)

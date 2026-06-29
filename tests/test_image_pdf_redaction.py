from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from xlent_scanner.image_pdf_redaction import redact_image_pdf


class _FakeOcrResult:
    txts = ("Ola Nordmann",)
    boxes = (
        [[20, 30], [120, 30], [120, 50], [20, 50]],
    )
    word_results = (
        (
            ("Ola", 0.99, [[20, 30], [55, 30], [55, 50], [20, 50]]),
            ("Nordmann", 0.99, [[60, 30], [120, 30], [120, 50], [60, 50]]),
        ),
    )


class _FakeOcrEngine:
    def __call__(self, img_content, *, return_word_box: bool = False):
        assert img_content
        assert return_word_box is True
        return _FakeOcrResult()


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_image_pdf(path: Path) -> None:
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 30, 120, 50), fill="black")

    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_image(page.rect, stream=_png_bytes(image))
    doc.save(str(path))
    doc.close()


def test_redact_image_pdf_masks_ocr_word_boxes(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    output = tmp_path / "scan-redacted.pdf"
    _write_image_pdf(source)

    stats = redact_image_pdf(
        source,
        {"Ola Nordmann": "[ANONYMISERT]"},
        output,
        dpi=72,
        padding_px=0,
        ocr_engine=_FakeOcrEngine(),
    )

    assert stats.pages == 1
    assert stats.redaction_count == 1
    assert stats.matched_values == ["Ola Nordmann"]
    assert stats.unmatched_values == []

    with fitz.open(str(output)) as doc:
        pixmap = doc[0].get_pixmap(alpha=False)
        redacted = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")

    assert redacted.getpixel((30, 40)) == (255, 255, 255)
    assert redacted.getpixel((115, 40)) == (255, 255, 255)

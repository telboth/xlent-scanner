"""Rasterbasert redaction av bilde-/OCR-PDF-er.

Vanlig PDF-redaction søker i PDF-ens tekstlag. Det fungerer ikke for innskannede
PDF-er der teksten bare finnes som piksler. Denne modulen renderer derfor hver
side til bilde, kjører OCR med koordinater, maskerer treff direkte i bildet og
bygger en ny bildebasert PDF av de maskerte sidene.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class _Target:
    original: str
    tokens: tuple[str, ...]
    compact: str


@dataclass(frozen=True)
class _OcrToken:
    text: str
    rect: tuple[float, float, float, float]


@dataclass
class ImagePdfRedactionStats:
    pages: int = 0
    redaction_count: int = 0
    matched_values: list[str] = field(default_factory=list)
    unmatched_values: list[str] = field(default_factory=list)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(text or ""))


def _compact(text: str) -> str:
    return "".join(_tokens(text))


def _targets(values: list[str]) -> list[_Target]:
    targets: list[_Target] = []
    seen: set[str] = set()
    for value in values:
        original = str(value or "").strip()
        if not original:
            continue
        tokens = _tokens(original)
        compact = "".join(tokens)
        if not tokens or not compact or compact in seen:
            continue
        seen.add(compact)
        targets.append(_Target(original=original, tokens=tokens, compact=compact))
    return targets


def _rect_from_box(box: Any) -> tuple[float, float, float, float] | None:
    if box is None:
        return None

    # RapidOCR bruker normalt fire punkter: [[x, y], ...].
    points: list[tuple[float, float]] = []
    try:
        for point in box:
            try:
                if len(point) >= 2:  # type: ignore[arg-type]
                    points.append((float(point[0]), float(point[1])))  # type: ignore[index]
            except TypeError:
                break
    except TypeError:
        points = []

    if len(points) >= 2:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    # Fallback for eventuelle [x0, y0, x1, y1]-bokser.
    try:
        if len(box) == 4:  # type: ignore[arg-type]
            x0, y0, x1, y1 = (float(box[index]) for index in range(4))  # type: ignore[index]
            return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    except (TypeError, ValueError):
        return None
    return None


def _iter_word_results(result: Any) -> list[tuple[str, tuple[float, float, float, float]]]:
    words: list[tuple[str, tuple[float, float, float, float]]] = []
    for line in getattr(result, "word_results", None) or ():
        for item in line or ():
            try:
                text = str(item[0] or "").strip()
                rect = _rect_from_box(item[2])
            except (IndexError, TypeError):
                continue
            if text and rect is not None:
                words.append((text, rect))
    return words


def _iter_line_results(result: Any) -> list[tuple[str, tuple[float, float, float, float]]]:
    lines: list[tuple[str, tuple[float, float, float, float]]] = []
    txts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    if txts is None or boxes is None:
        return lines
    for text, box in zip(txts, boxes, strict=False):
        rect = _rect_from_box(box)
        text = str(text or "").strip()
        if text and rect is not None:
            lines.append((text, rect))
    return lines


def _union_rect(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(rect[0] for rect in rects),
        min(rect[1] for rect in rects),
        max(rect[2] for rect in rects),
        max(rect[3] for rect in rects),
    )


def _dedupe_rects(rects: list[tuple[float, float, float, float]]) -> list[tuple[float, float, float, float]]:
    seen: set[tuple[int, int, int, int]] = set()
    unique: list[tuple[float, float, float, float]] = []
    for rect in rects:
        key = tuple(round(value) for value in rect)
        if key in seen:
            continue
        seen.add(key)
        unique.append(rect)
    return unique


def _find_redaction_rects(
    result: Any,
    targets: list[_Target],
) -> tuple[list[tuple[float, float, float, float]], set[str]]:
    rects: list[tuple[float, float, float, float]] = []
    matched: set[str] = set()

    flat_tokens: list[_OcrToken] = []
    for text, rect in _iter_word_results(result):
        for token in _tokens(text):
            flat_tokens.append(_OcrToken(token, rect))

    for target in targets:
        width = len(target.tokens)
        if width == 0 or len(flat_tokens) < width:
            continue
        for index in range(0, len(flat_tokens) - width + 1):
            window = flat_tokens[index:index + width]
            if tuple(token.text for token in window) == target.tokens:
                rects.append(_union_rect([token.rect for token in window]))
                matched.add(target.compact)

    # Fallback: maskér hele OCR-linjen hvis vi ikke fant ordvinduer. Dette er
    # mindre presist, men bedre enn å produsere en "anonymisert" bilde-PDF uten
    # maskering når OCR-motoren bare returnerer linjebokser.
    for target in targets:
        if target.compact in matched or len(target.compact) < 4:
            continue
        for text, rect in _iter_line_results(result):
            if target.compact in _compact(text):
                rects.append(rect)
                matched.add(target.compact)

    return _dedupe_rects(rects), matched


def _png_bytes_from_image(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_masks(
    image: Any,
    rects: list[tuple[float, float, float, float]],
    *,
    padding_px: int,
    fill: tuple[int, int, int],
) -> None:
    from PIL import ImageDraw  # type: ignore[import-untyped]  # noqa: PLC0415

    draw = ImageDraw.Draw(image)
    width, height = image.size
    for x0, y0, x1, y1 in rects:
        padded = (
            max(0, int(x0) - padding_px),
            max(0, int(y0) - padding_px),
            min(width, int(x1) + padding_px),
            min(height, int(y1) + padding_px),
        )
        draw.rectangle(padded, fill=fill)


def redact_image_pdf(
    source: Path,
    replacements: dict[str, str],
    output: Path,
    *,
    strip_annotations: bool = False,
    dpi: int = 200,
    padding_px: int = 4,
    mask_fill: tuple[int, int, int] = (255, 255, 255),
    ocr_engine: Any | None = None,
) -> ImagePdfRedactionStats:
    """Maskér funn i en bildebasert PDF og skriv ny rasterisert PDF.

    ``replacements`` brukes som kilde til verdiene som skal fjernes; selve
    erstatningsteksten tegnes ikke inn i bildet. Maskering skjer med en heldekkende
    hvit boks over OCR-boksen til verdien.
    """
    if source.suffix.lower() != ".pdf":
        raise ValueError("Rasterbasert PDF-redaction støtter bare PDF.")
    if dpi < 72:
        raise ValueError("DPI må være minst 72.")

    target_values = _targets(list(replacements.keys()))
    if not target_values and not strip_annotations:
        raise ValueError("Ingen verdier å maskere.")

    if ocr_engine is None:
        from xlent_scanner.scanner import _get_image_ocr_engine  # noqa: PLC0415

        ocr_engine = _get_image_ocr_engine()

    import fitz  # type: ignore[import-untyped]  # noqa: PLC0415
    from PIL import Image  # type: ignore[import-untyped]  # noqa: PLC0415

    stats = ImagePdfRedactionStats()
    matched_compact: set[str] = set()
    matrix = fitz.Matrix(dpi / 72, dpi / 72)

    source_doc = fitz.open(str(source))
    output_doc = fitz.open()
    try:
        for page in source_doc:
            stats.pages += 1
            pixmap = page.get_pixmap(matrix=matrix, alpha=False, annots=not strip_annotations)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")

            rects: list[tuple[float, float, float, float]] = []
            if target_values:
                ocr_result = ocr_engine(_png_bytes_from_image(image), return_word_box=True)
                rects, matched = _find_redaction_rects(ocr_result, target_values)
                matched_compact.update(matched)
                _draw_masks(image, rects, padding_px=padding_px, fill=mask_fill)
                stats.redaction_count += len(rects)

            out_page = output_doc.new_page(width=page.rect.width, height=page.rect.height)
            out_page.insert_image(out_page.rect, stream=_png_bytes_from_image(image))

        stats.matched_values = [
            target.original
            for target in target_values
            if target.compact in matched_compact
        ]
        stats.unmatched_values = [
            target.original
            for target in target_values
            if target.compact not in matched_compact
        ]
        output_doc.save(str(output), garbage=4, deflate=True)
    finally:
        output_doc.close()
        source_doc.close()

    return stats

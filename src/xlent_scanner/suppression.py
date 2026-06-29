"""Intern sporing av kandidater som bevisst forkastes av postfiltre."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from xlent_scanner.models import SuppressedFinding

_current_suppressed: ContextVar[list[SuppressedFinding] | None] = ContextVar(
    "xlent_scanner_suppressed_findings",
    default=None,
)


@contextmanager
def capture_suppressed_findings() -> Iterator[list[SuppressedFinding]]:
    """Fang forkastede kandidater for én scan uten global delt state."""
    captured: list[SuppressedFinding] = []
    token = _current_suppressed.set(captured)
    try:
        yield captured
    finally:
        _current_suppressed.reset(token)


def record_suppressed(
    category: str,
    text: str,
    context: str = "",
    reason: str = "",
    source: str = "Regelbasert",
) -> None:
    captured = _current_suppressed.get()
    if captured is None:
        return
    text = str(text or "").strip()
    if not text:
        return
    captured.append(
        SuppressedFinding(
            category=str(category or ""),
            text=text,
            context=str(context or ""),
            reason=str(reason or ""),
            source=str(source or "Regelbasert"),
        )
    )

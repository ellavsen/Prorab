"""Extraction <-> словарь. Одно место, где знают про имена полей на проводе.

Через это же проходят записанные фикстуры и размеченный eval-набор, поэтому
формат у них один и разойтись они не могут.
"""

from __future__ import annotations

from dataclasses import asdict

from .candidates import (
    Extraction,
    ExtractionStatus,
    IgnoredFragment,
    PositionCandidate,
    Price,
    Quantity,
)


def _text(value) -> str:
    return "" if value is None else str(value)


def candidate_from_dict(data: dict) -> PositionCandidate:
    qty = data.get("qty") or {}
    price = data.get("price") or {}
    return PositionCandidate(
        name=_text(data.get("name")),
        qty=Quantity(status=_text(qty.get("status")) or "missing",
                     value=_text(qty.get("value"))),
        price=Price(status=_text(price.get("status")) or "missing",
                    scope=_text(price.get("scope")) or "unknown",
                    value=_text(price.get("value"))),
        unit=_text(data.get("unit")),
        unit_spoken=_text(data.get("unit_spoken")),
        category=_text(data.get("category")) or "unknown",
        source_quote=_text(data.get("source_quote")),
        confidence=_text(data.get("confidence")) or "medium",
    )


def extraction_from_dict(data: dict) -> Extraction:
    """Собирает ответ. Модель шлёт ignored_fragments, наш asdict — ignored."""
    fragments = data.get("ignored_fragments") or data.get("ignored") or []
    return Extraction(
        status=_text(data.get("status")) or ExtractionStatus.EMPTY,
        positions=tuple(candidate_from_dict(item) for item in data.get("positions") or []),
        ignored=tuple(
            IgnoredFragment(quote=_text(f.get("quote")), reason=_text(f.get("reason")))
            for f in fragments
        ),
    )


def extraction_to_dict(extraction: Extraction) -> dict:
    return asdict(extraction)

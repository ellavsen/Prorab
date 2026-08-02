"""Инварианты, которые JSON-схема выразить не может.

Строгая схема гарантирует форму ответа, но не его правдивость: она не проверит
ни диапазоны из money.md, ни то, что процитированные слова вообще были во
входе. Это делает код — на границе, до всякого расчёта.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from smeta_core import Category, check_price, check_quantity, parse_price, parse_quantity

from .candidates import (
    Extraction,
    ExtractionStatus,
    FieldStatus,
    PositionCandidate,
    PriceScope,
    to_position,
)

# Какая доля процитированного должна дословно найтись во входе.
QUOTE_RATIO = 0.8

_FIELD_STATUSES = {s.value for s in FieldStatus}
_SCOPES = {s.value for s in PriceScope}


def _flat(text: str) -> str:
    return " ".join((text or "").lower().split())


def quote_is_grounded(quote: str, source: str | None) -> bool:
    """Защита от выдумывания: процитированное должно быть во входе.

    source None — вход не текстовый (фото), проверять нечем.
    """
    if source is None:
        return True
    needle, haystack = _flat(quote), _flat(source)
    if not needle:
        return False
    if needle in haystack:
        return True
    match = SequenceMatcher(None, needle, haystack).find_longest_match(
        0, len(needle), 0, len(haystack)
    )
    return match.size / len(needle) >= QUOTE_RATIO


def check_candidate(
    candidate: PositionCandidate, source: str | None, fallback: Category
) -> str | None:
    """None — кандидата можно показывать как позицию; иначе причина, почему нет."""
    if not quote_is_grounded(candidate.source_quote, source):
        return "не нашла этих слов в исходном тексте"
    try:
        to_position(candidate, fallback)
    except ValueError as error:
        return str(error)
    return None


def _field_problems(index: int, candidate: PositionCandidate) -> list[str]:
    problems = []
    where = f"позиция {index}"

    for name, field in (("qty", candidate.qty), ("price", candidate.price)):
        if field.status not in _FIELD_STATUSES:
            problems.append(f"{where}: неизвестный статус {name}: {field.status!r}")
        # missing ⇔ пусто. Иначе «не названо» и «ноль» снова сливаются.
        if (field.status == FieldStatus.MISSING) != (not field.value):
            problems.append(f"{where}: {name}.status={field.status}, а value={field.value!r}")

    if candidate.price.scope not in _SCOPES:
        problems.append(f"{where}: неизвестный scope {candidate.price.scope!r}")

    if candidate.qty.value:
        try:
            check_quantity(parse_quantity(candidate.qty.value))
        except ValueError as error:
            problems.append(f"{where}: {error}")
    if candidate.price.value:
        try:
            check_price(parse_price(candidate.price.value))
        except ValueError as error:
            problems.append(f"{where}: {error}")

    if not candidate.name.strip():
        problems.append(f"{where}: пустое наименование")
    return problems


def validate_extraction(extraction: Extraction, source: str | None = None) -> list[str]:
    """Список нарушений контракта. Пустой список — ответ модели годен."""
    problems: list[str] = []

    if extraction.status == ExtractionStatus.OK and not extraction.positions:
        problems.append("status=ok, но позиций нет")
    if extraction.status != ExtractionStatus.OK and extraction.positions:
        problems.append(f"status={extraction.status}, но позиции есть")

    for index, candidate in enumerate(extraction.positions, start=1):
        problems.extend(_field_problems(index, candidate))
        if not quote_is_grounded(candidate.source_quote, source):
            problems.append(f"позиция {index}: цитата не найдена во входе")
    return problems

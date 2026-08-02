"""Стаб-провайдер: детерминированный, без сети и без ключей.

Нужен для двух вещей: тесты не должны ходить в интернет, и проект обязан
подниматься в DEMO-режиме с нулём ключей (конституция, правило 7).

Это не модель и не притворяется ею. Извлечение здесь — разбор канонической
строки «Наименование, количество, цена» плюс один шаблон живой речи вида
«побелка 150 квадратов по 3000». В eval стаб служит нижней границей: то, что
даёт голая регулярка без модели (ADR-014).
"""

from __future__ import annotations

import re

from smeta_core import AmbiguousLine, Category, normalize_unit, parse_position_line

from .candidates import (
    Confidence,
    Extraction,
    ExtractionStatus,
    FieldStatus,
    PositionCandidate,
    Price,
    PriceScope,
    Quantity,
)

# «побелка 150 квадратов по 3000» — наименование, число, необязательная
# единица, «по», цена. Наименование не содержит цифр и разделителей.
# Единица может содержать цифры («м2»), поэтому от «по» её отделяет только
# явный запрет: иначе предлог был бы прочитан как единица измерения.
_PHRASE = re.compile(
    r"(?P<name>[^\d,;\n]+?)\s*(?P<qty>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>(?!по\b)[^\s,;]*)\s*по\s*(?P<price>\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_LEADING_CONJUNCTION = re.compile(r"^\s*(?:и|а также|плюс)\s+", re.IGNORECASE)

# Что «слышит» и «видит» стаб. Значения постоянные: демо обязано быть
# воспроизводимым, а пользователю бот прямо говорит, что это демо-режим.
DEMO_TRANSCRIPT = "Побелка 150 квадратов по 3000, гвозди 1000 штук по 20"


def _stated(name, qty, price, unit_spoken, quote) -> PositionCandidate:
    return PositionCandidate(
        name=name,
        qty=Quantity(status=FieldStatus.STATED, value=qty),
        price=Price(status=FieldStatus.STATED, scope=PriceScope.PER_UNIT, value=price),
        unit=normalize_unit(unit_spoken),
        unit_spoken=unit_spoken,
        source_quote=quote,
        confidence=Confidence.LOW,
    )


DEMO_INVOICE = (
    _stated("Цемент М500", "20", "450", "шт", "Цемент М500, 20 шт, 450,00"),
    _stated("Песок карьерный", "3", "1200", "м3", "Песок карьерный, 3 м3, 1200,00"),
)


def _clean(name: str) -> str:
    return _LEADING_CONJUNCTION.sub("", name).strip(" -–—:").strip()


def _from_canonical(line: str) -> PositionCandidate | None:
    """Строка формата «Наименование, количество, цена», если она такова.

    Категорию стаб не угадывает: её подставит вызывающий из выбора человека.
    """
    try:
        position = parse_position_line(line, Category.MATERIAL)
    except (AmbiguousLine, ValueError):
        return None
    return _stated(position.name, str(position.qty), str(position.price),
                   position.unit, line)


def _from_speech(line: str) -> list[PositionCandidate]:
    found = []
    for match in _PHRASE.finditer(line):
        name = _clean(match.group("name"))
        if not name:
            continue
        found.append(_stated(
            name=name[:1].upper() + name[1:],
            qty=match.group("qty").replace(",", "."),
            price=match.group("price").replace(",", "."),
            unit_spoken=match.group("unit"),
            quote=match.group(0).strip(),
        ))
    return found


class StubProvider:
    """Провайдер DEMO-режима. Ничего не знает про сеть."""

    name = "stub"

    def transcribe(self, audio: bytes, filename: str) -> str:
        return DEMO_TRANSCRIPT

    def extract(self, text: str) -> Extraction:
        found: list[PositionCandidate] = []
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            canonical = _from_canonical(line)
            found.extend([canonical] if canonical else _from_speech(line))
        return _wrap(found)

    def extract_from_image(self, image: bytes, media_type: str) -> Extraction:
        return _wrap(list(DEMO_INVOICE))


def _wrap(found: list[PositionCandidate]) -> Extraction:
    status = ExtractionStatus.OK if found else ExtractionStatus.EMPTY
    return Extraction(status=status, positions=tuple(found))

"""Шапка документа — одна на все поверхности.

PDF и публичная страница подписывают смету одинаково: «Смета № 3, ред. 2»,
«3 августа 2026 · Отправлена заказчику». Если бы каждая поверхность строила эту
строку сама, они разошлись бы — сначала в пробеле, потом в дате, потом в
номере редакции, и заказчик получил бы два документа, про которые нельзя
сказать, один это документ или два.

Здесь только текст шапки. Денег здесь нет вовсе.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")


@dataclass(frozen=True)
class DocumentMeta:
    """Шапка документа. Ничего о владельце здесь нет и быть не может."""

    number: int
    version: int
    title: str
    on: date
    work_rate: Decimal
    material_rate: Decimal
    status: str = ""


def spell_date(on: date) -> str:
    return f"{on.day} {MONTHS[on.month - 1]} {on.year}"


def document_title(meta: DocumentMeta) -> str:
    return f"Смета № {meta.number}, ред. {meta.version}"


def document_subtitle(meta: DocumentMeta) -> str:
    """Дата и статус через разделитель. Пустой статус не оставляет хвоста."""
    return " · ".join(part for part in (spell_date(meta.on), meta.status) if part)

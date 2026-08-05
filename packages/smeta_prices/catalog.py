"""Справочник позиций: канон, единица, категория, синонимы. Цен в нём нет.

Цены здесь нет ни одной строки, и это решение, а не пробел. Справочная цена
«по здравому смыслу» — выдуманное число в продукте про деньги: прораб, увидев
цемент по 7 300 там, где у него 5 800, закроет бота навсегда, и пометка
«справочная» этого не изменит (ADR-017).

А вот единица, категория и синонимы — факты: цемент меряют в тоннах, ЦЕМ II
42.5 это М500, плитку считают в квадратах. Они и лежат в файле.

Отдельного словаря переписываний нет: каждый синоним принадлежит своей
позиции, а значит и своей категории. Это и есть требование «правила
переписывания привязаны к категории», выполненное строением данных.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from smeta_core import UNITS

from .match import FUZZY_CUTOFF, candidates
from .normalize import normalize_name

__all__ = ["CATALOG", "DATA", "FUZZY_CUTOFF", "KINDS", "Catalog", "CatalogError",
           "Item", "build", "load"]

DATA = Path(__file__).parent / "catalog.json"

KINDS = frozenset({"work", "material"})


class CatalogError(ValueError):
    """Справочник противоречив. Импорт должен упасть, а не разрешить это молча."""


@dataclass(frozen=True)
class Item:
    name: str
    unit: str
    kind: str
    aliases: tuple[str, ...] = ()

    def spellings(self) -> list[str]:
        """Все написания позиции в нормализованном виде, включая её имя."""
        return [key for key in (normalize_name(raw)
                                for raw in (self.name, *self.aliases)) if key]


@dataclass(frozen=True)
class Catalog:
    items: tuple[Item, ...]
    index: dict[str, Item]

    def find(self, raw: str) -> Item | None:
        """Позиция по любому её написанию. Не уверен — None, а не догадка."""
        key = normalize_name(raw)
        if not key:
            return None
        exact = self.index.get(key)
        if exact is not None:
            return exact
        return self._closest(key)

    def _closest(self, key: str) -> Item | None:
        """Опечатки и хвосты — двумя ступенями подряд (match.py, ADR-027).

        Кандидаты сводятся к позициям, а не к написаниям: два синонима одной
        позиции — это один ответ, а не повод промолчать. Две разные позиции —
        молчим.

        difflib из стандартной библиотеки, а не RapidFuzz: на 173 позициях и
        строках в три слова разницы в скорости нет, а зависимость есть.
        Появится реальный поток — заменим по замеру, а не по ожиданию.
        """
        found = {self.index[match] for match in candidates(key, self.index)}
        return next(iter(found)) if len(found) == 1 else None


def build(raw_items: list[dict]) -> Catalog:
    """Список из файла -> справочник с проверенным индексом.

    Проверяется всё, что может разойтись молча: единица вне канона ядра,
    неизвестная категория, одно написание у двух позиций. Последнее — тот же
    класс ошибки, что дубль «т.» в Sprint 5, только на именах.
    """
    items = tuple(
        Item(name=raw["name"], unit=raw["unit"], kind=raw["kind"],
             aliases=tuple(raw.get("aliases", ())))
        for raw in raw_items
    )
    index: dict[str, Item] = {}
    for item in items:
        if item.unit not in UNITS:
            raise CatalogError(f"{item.name}: единица {item.unit!r} вне канона ядра")
        if item.kind not in KINDS:
            raise CatalogError(f"{item.name}: категория {item.kind!r} неизвестна")
        for key in item.spellings():
            existing = index.get(key)
            if existing is not None and existing is not item:
                raise CatalogError(
                    f"написание {key!r} принадлежит и {existing.name!r}, и {item.name!r}"
                )
            index[key] = item
    return Catalog(items=items, index=index)


def load(path: Path | str = DATA) -> Catalog:
    return build(json.loads(Path(path).read_text(encoding="utf-8")))


CATALOG = load()

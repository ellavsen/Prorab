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

__all__ = ["CATALOG", "DATA", "DAY_UNITS", "FUZZY_CUTOFF", "KINDS", "Catalog",
           "CatalogError", "Item", "build", "load"]

DATA = Path(__file__).parent / "catalog.json"

KINDS = frozenset({"work", "material"})

# Единицы повремёнки. Позиция, которая ими меряется, обязана сказать о себе,
# труд это человека или аренда железа: и то и другое — «work» за «смену», а
# исполнитель бывает только у первого (ADR-029).
DAY_UNITS = frozenset({"час", "смена"})


class CatalogError(ValueError):
    """Справочник противоречив. Импорт должен упасть, а не разрешить это молча."""


@dataclass(frozen=True)
class Item:
    name: str
    unit: str
    kind: str
    aliases: tuple[str, ...] = ()
    # Труд человека, а не аренда. Значение имеет смысл только у позиций в
    # часах и сменах; у остальных оно False и ни на что не влияет.
    labor: bool = False

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

    def takes_performer(self, raw: str) -> bool:
        """Ставится ли на такую позицию исполнитель.

        Нет — только у известной аренды: «Аренда бетономешалки» это work со
        сменой в единицах, и правило «час или смена → это ставка человека»
        затащило бы её в человеко-дни (ADR-029).

        Позиция, которой справочник не знает, исполнителя принимает: весь
        хвост разовых работ живёт именно там, и молчать про него — значит
        отобрать поле у большинства строк реальной сметы.
        """
        item = self.find(raw)
        return item is None or item.labor or item.unit not in DAY_UNITS

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
    for raw in raw_items:
        # Признак обязателен, а не подразумевается. Умолчание «не труд» было
        # бы безопаснее умолчания «труд», но оба молчат, а забытая позиция в
        # сменах — это либо человек без исполнителя, либо перфоратор с ним.
        if raw["unit"] in DAY_UNITS and "labor" not in raw:
            raise CatalogError(
                f"{raw['name']}: единица {raw['unit']!r} — скажи явно, "
                f"труд это человека или аренда (labor)"
            )
        if raw.get("labor") and raw["unit"] not in DAY_UNITS:
            raise CatalogError(
                f"{raw['name']}: labor стоит у позиции в {raw['unit']!r}, "
                f"а ставка человека меряется часом или сменой"
            )

    items = tuple(
        Item(name=raw["name"], unit=raw["unit"], kind=raw["kind"],
             aliases=tuple(raw.get("aliases", ())), labor=bool(raw.get("labor")))
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

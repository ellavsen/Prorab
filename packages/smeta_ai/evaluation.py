"""Метрика извлечения: точное совпадение после нормализации.

Позиция засчитана, если совпали количество, цена, их статусы, scope, единица
и категория — точно, а наименование — после приведения регистра, пробелов и
«ё». Нечёткое сравнение наименований дало бы более лестные цифры и менее
честные.

`unit_spoken` в ключ сравнения НЕ входит: это провенанс для документа, а не
предмет замера. Сверяется канон, потому что именно он однозначен.

Считаются обе стороны: пропущенная позиция бьёт по recall, выдуманная — по
precision. Одной «доли извлечённого» мало: модель, выдающая всё подряд, имела
бы отличный recall.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from smeta_core import normalize_unit, parse_price, parse_quantity

from .candidates import Extraction, PositionCandidate
from .serialize import extraction_from_dict

_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    return _SPACES.sub(" ", (name or "").strip().lower().replace("ё", "е"))


def _number(value: str, parse):
    """Пусто -> None, разбирается -> Decimal, мусор -> метка, которая не совпадёт."""
    if not value:
        return None
    try:
        return parse(value)
    except ValueError:
        return ("invalid", value)


def position_key(candidate: PositionCandidate) -> tuple:
    return (
        normalize_name(candidate.name),
        _number(candidate.qty.value, parse_quantity),
        candidate.qty.status,
        _number(candidate.price.value, parse_price),
        candidate.price.status,
        candidate.price.scope,
        normalize_unit(candidate.unit) or normalize_unit(candidate.unit_spoken),
        str(candidate.category).strip().lower(),
    )


def _describe(candidate: PositionCandidate) -> str:
    key = position_key(candidate)
    qty, price, unit = key[1], key[3], key[6] or "?"
    return (f"{key[0]} {qty if qty is not None else '—'} {unit} × "
            f"{price if price is not None else '—'} [{key[7]}/{key[5]}]")


def compare(expected: list[PositionCandidate], predicted: list[PositionCandidate]):
    """Сопоставление мультимножеств: дубли не засчитываются дважды."""
    expected_keys = [position_key(c) for c in expected]
    predicted_keys = [position_key(c) for c in predicted]
    common = Counter(expected_keys) & Counter(predicted_keys)
    matched = sum(common.values())

    def unmatched(keys, items) -> list[str]:
        """Счётчик расходуется: два одинаковых ожидания и одно попадание —
        это одно совпадение и один промах, а не два совпадения."""
        budget = Counter(common)
        out = []
        for key, item in zip(keys, items, strict=True):
            if budget[key] > 0:
                budget[key] -= 1
                continue
            out.append(_describe(item))
        return out

    return matched, unmatched(expected_keys, expected), unmatched(predicted_keys, predicted)


def check_asserts(rules: dict, extraction: Extraction) -> list[str]:
    """Явные запреты примера. `no_position_qty` ловит счёт вместо извлечения.

    «Комната три на четыре» не должна дать qty 12: перемножать — не работа
    модели (продуктовый тезис).
    """
    failures = []
    for forbidden in rules.get("no_position_qty", []):
        wanted = _number(str(forbidden), parse_quantity)
        for candidate in extraction.positions:
            if _number(candidate.qty.value, parse_quantity) == wanted:
                failures.append(f"количество {forbidden} — модель посчитала сама")
    return failures


@dataclass
class ExampleResult:
    example_id: str
    tags: tuple[str, ...]
    expected: int
    predicted: int
    matched: int
    status_matches: bool
    missed: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    assert_failures: list[str] = field(default_factory=list)


@dataclass
class Report:
    results: list[ExampleResult] = field(default_factory=list)

    @property
    def expected(self) -> int:
        return sum(r.expected for r in self.results)

    @property
    def predicted(self) -> int:
        return sum(r.predicted for r in self.results)

    @property
    def matched(self) -> int:
        return sum(r.matched for r in self.results)

    @property
    def recall(self) -> float:
        return 1.0 if self.expected == 0 else self.matched / self.expected

    @property
    def precision(self) -> float:
        return 1.0 if self.predicted == 0 else self.matched / self.predicted

    @property
    def exact_examples(self) -> int:
        """Примеров, разобранных целиком, без лишнего и без нарушенных запретов."""
        return sum(
            1 for r in self.results
            if r.matched == r.expected and r.matched == r.predicted
            and r.status_matches and not r.assert_failures
        )

    @property
    def assert_failures(self) -> list[str]:
        return [f"[{r.example_id}] {text}" for r in self.results for text in r.assert_failures]

    def tags(self) -> list[str]:
        return sorted({tag for r in self.results for tag in r.tags})

    def by_tag(self, tag: str) -> Report:
        return Report([r for r in self.results if tag in r.tags])


def load_dataset(path: Path | str) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def expected_extraction(example: dict) -> Extraction:
    return extraction_from_dict(example["expected"])


def evaluate(extractor, dataset: list[dict]) -> Report:
    """Прогоняет набор через извлекатель и считает метрику."""
    report = Report()
    for example in dataset:
        expected = expected_extraction(example)
        predicted = extractor.extract(example["input"])
        matched, missed, invented = compare(
            list(expected.positions), list(predicted.positions)
        )
        report.results.append(ExampleResult(
            example_id=example["id"],
            tags=tuple(example.get("tags", ())),
            expected=len(expected.positions),
            predicted=len(predicted.positions),
            matched=matched,
            status_matches=expected.status == predicted.status,
            missed=missed,
            invented=invented,
            assert_failures=check_asserts(example.get("assert", {}), predicted),
        ))
    return report

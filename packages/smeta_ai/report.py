"""Печать и разбор отчёта eval.

Живёт рядом с ExampleResult намеренно. Форматтер лежал в scripts/run_eval.py,
разъехался с переименованием поля и уронил процесс уже ПОСЛЕ 89 платных
вызовов. Здесь его накрывают те же тесты, что и метрику.
"""

from __future__ import annotations

from collections import Counter

from .candidates import PositionCandidate
from .evaluation import Report, describe, normalize_name, position_key

# Поля ключа сравнения в том же порядке, в каком их отдаёт position_key.
KEY_FIELDS = (
    "name", "qty.value", "qty.status", "price.value",
    "price.status", "price.scope", "unit", "category",
)


def _pair_up(missed: list[PositionCandidate], invented: list[PositionCandidate]):
    """Сводит промахи с лишними по наименованию.

    Совпало наименование — значит позиция найдена, но каким-то полем
    разошлась. Не совпало — потеряна или выдумана целиком.
    """
    remaining = list(invented)
    for expected in missed:
        same_name = next(
            (c for c in remaining
             if normalize_name(c.name) == normalize_name(expected.name)),
            None,
        )
        if same_name is not None:
            remaining.remove(same_name)
            yield expected, same_name
        else:
            yield expected, None
    for extra in remaining:
        yield None, extra


def field_disagreements(report: Report) -> Counter:
    """Сколько раз разошлось каждое поле. Даёт ответ «чинить промптом или моделью»."""
    tally: Counter = Counter()
    for result in report.results:
        for expected, predicted in _pair_up(result.missed, result.invented):
            if expected is None:
                tally["позиция выдумана"] += 1
                continue
            if predicted is None:
                tally["позиция пропущена"] += 1
                continue
            left, right = position_key(expected), position_key(predicted)
            for name, a, b in zip(KEY_FIELDS, left, right, strict=True):
                if a != b:
                    tally[name] += 1
    return tally


def tag_rows(report: Report) -> list[dict]:
    """Метрика по каждому тегу отдельно."""
    rows = []
    for tag in report.tags():
        part = report.by_tag(tag)
        rows.append({
            "tag": tag,
            "examples": len(part.results),
            "expected": part.expected,
            "predicted": part.predicted,
            "matched": part.matched,
            "recall": round(part.recall, 3),
            "precision": round(part.precision, 3),
            "exact": part.exact_examples,
        })
    return sorted(rows, key=lambda row: row["recall"])


def report_to_dict(report: Report) -> dict:
    """Отчёт как данные — чтобы его можно было перечитать, а не только прочесть."""
    return {
        "examples": len(report.results),
        "expected": report.expected,
        "predicted": report.predicted,
        "matched": report.matched,
        "recall": round(report.recall, 4),
        "precision": round(report.precision, 4),
        "exact_examples": report.exact_examples,
        "assert_failures": report.assert_failures,
        "by_tag": tag_rows(report),
        "by_field": dict(field_disagreements(report).most_common()),
        "results": [
            {
                "id": r.example_id,
                "tags": list(r.tags),
                "expected": r.expected,
                "predicted": r.predicted,
                "matched": r.matched,
                "status_matches": r.status_matches,
                "missed": [describe(c) for c in r.missed],
                "invented": [describe(c) for c in r.invented],
                "assert_failures": r.assert_failures,
            }
            for r in report.results
        ],
    }


def format_report(report: Report, verbose: bool = False) -> str:
    """Отчёт текстом. Ничего не печатает сам — возвращает строку."""
    out = [
        f"Примеров: {len(report.results)}",
        f"Ожидалось позиций: {report.expected}, извлечено: {report.predicted}, "
        f"совпало: {report.matched}",
        f"recall    {report.recall:.3f}",
        f"precision {report.precision:.3f}",
        f"целиком верных примеров: {report.exact_examples} из {len(report.results)}",
    ]

    if report.assert_failures:
        out.append("\nНарушены явные запреты примеров:")
        out.extend(f"  {text}" for text in report.assert_failures)

    rows = tag_rows(report)
    if rows:
        out.append("\nПо тегам (худшие сверху):")
        out.append(f"  {'тег':<12} {'прим':>5} {'ожид':>5} {'совп':>5} "
                   f"{'recall':>7} {'precis':>7} {'целиком':>8}")
        for row in rows:
            out.append(
                f"  {row['tag']:<12} {row['examples']:>5} {row['expected']:>5} "
                f"{row['matched']:>5} {row['recall']:>7.3f} {row['precision']:>7.3f} "
                f"{row['exact']:>8}"
            )

    fields = field_disagreements(report)
    if fields:
        out.append("\nПоле -> число расхождений:")
        out.extend(f"  {name:<20} {count}" for name, count in fields.most_common())

    if verbose:
        for result in report.results:
            if not (result.missed or result.invented or result.assert_failures):
                continue
            out.append(f"\n[{result.example_id}] {', '.join(result.tags) or '—'}")
            out.extend(f"  ожидалось: {describe(c)}" for c in result.missed)
            out.extend(f"  получено:  {describe(c)}" for c in result.invented)
            out.extend(f"  запрет:    {text}" for text in result.assert_failures)

    return "\n".join(out)

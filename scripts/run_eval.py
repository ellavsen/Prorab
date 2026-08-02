#!/usr/bin/env python3
"""Прогон eval-набора и метрика извлечения.

    python scripts/run_eval.py            # проигрывание записанных ответов
    python scripts/run_eval.py --record   # запись живых ответов (нужен ключ)
    python scripts/run_eval.py --stub     # нижняя граница: без модели вообще

Порог проверяется только на записанных ответах модели. На стабе он не имеет
смысла: стаб измеряет стаб (ADR-014).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages"))

from smeta_ai import OpenAIProvider, RecordedProvider, StubProvider  # noqa: E402
from smeta_ai.evaluation import evaluate, load_dataset  # noqa: E402

EVAL_DIR = ROOT / "tests" / "eval"
FIXTURES = EVAL_DIR / "fixtures"


def load_config() -> dict:
    return json.loads((EVAL_DIR / "config.json").read_text(encoding="utf-8"))


def build_extractor(mode: str, model: str):
    if mode == "stub":
        return StubProvider()

    inner = None
    if mode == "record":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise SystemExit("Для записи нужен OPENAI_API_KEY. Запись живая и платная.")
        inner = OpenAIProvider(api_key=key, model=model)
    return RecordedProvider(FIXTURES, model=model, inner=inner)


def print_report(report, verbose: bool) -> None:
    print(f"Примеров: {len(report.results)}")
    print(f"Ожидалось позиций: {report.expected}, извлечено: {report.predicted}, "
          f"совпало: {report.matched}")
    print(f"recall    {report.recall:.3f}")
    print(f"precision {report.precision:.3f}")
    print(f"целиком верных примеров: {report.exact_examples} из {len(report.results)}")

    if not verbose:
        return
    for result in report.results:
        if result.missed or result.invented:
            print(f"\n[{result.example_id}] {result.kind}")
            for item in result.missed:
                print(f"  пропущено: {item}")
            for item in result.invented:
                print(f"  лишнее:    {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="записать живые ответы")
    parser.add_argument("--stub", action="store_true", help="прогнать на стабе")
    parser.add_argument("--verbose", action="store_true", help="показать расхождения")
    args = parser.parse_args()

    config = load_config()
    mode = "record" if args.record else ("stub" if args.stub else "replay")
    dataset = load_dataset(EVAL_DIR / "dataset.jsonl")
    report = evaluate(build_extractor(mode, config["model"]), dataset)

    print(f"Режим: {mode}, модель: {config['model']}")
    print_report(report, args.verbose or mode != "stub")

    if mode == "stub":
        print("\nЭто нижняя граница без модели, порог к ней не применяется.")
        return 0

    failed = (
        report.recall < config["min_recall"] or report.precision < config["min_precision"]
    )
    if failed:
        print(f"\nНиже порога: recall ≥ {config['min_recall']}, "
              f"precision ≥ {config['min_precision']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

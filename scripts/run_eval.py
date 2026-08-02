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
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages"))

from smeta_ai import PROMPT_VERSION, OpenAIProvider, RecordedProvider, StubProvider  # noqa: E402
from smeta_ai.evaluation import evaluate, load_dataset  # noqa: E402
from smeta_ai.recorded import version_dir  # noqa: E402
from smeta_ai.report import format_comparison, format_report, report_to_dict  # noqa: E402

EVAL_DIR = ROOT / "tests" / "eval"
FIXTURES = EVAL_DIR / "fixtures"
LAST_REPORT = EVAL_DIR / "last_report.json"


def load_config() -> dict:
    return json.loads((EVAL_DIR / "config.json").read_text(encoding="utf-8"))


def replay(model: str, prompt_version: str = PROMPT_VERSION, inner=None):
    """Проигрыватель ответов конкретной версии промпта."""
    return RecordedProvider(
        version_dir(FIXTURES, prompt_version), model=model, inner=inner,
        prompt_version=prompt_version,
    )


def build_extractor(mode: str, model: str):
    if mode == "stub":
        return StubProvider()

    inner = None
    if mode == "record":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise SystemExit("Для записи нужен OPENAI_API_KEY. Запись живая и платная.")
        inner = OpenAIProvider(api_key=key, model=model)
    return replay(model, inner=inner)


def run_comparison(config: dict, dataset: list[dict], versions: list[str]) -> int:
    """Две версии промпта на одном наборе. Ничего не записывает."""
    left, right = versions
    reports = {
        version: evaluate(replay(config["model"], version), dataset)
        for version in (left, right)
    }
    print(f"Сравнение промптов на одном наборе, модель {config['model']}\n")
    print(format_comparison(f"v{left}", reports[left], f"v{right}", reports[right]))
    return 0


def save_report(report) -> None:
    """Отчёт на диск раньше печати: форматтер не должен стоить прогона."""
    LAST_REPORT.write_text(
        json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="записать живые ответы")
    parser.add_argument("--stub", action="store_true", help="прогнать на стабе")
    parser.add_argument("--verbose", action="store_true", help="показать расхождения")
    parser.add_argument(
        "--compare", nargs=2, metavar=("СТАРАЯ", "НОВАЯ"),
        help="сравнить две версии промпта на одном наборе: --compare v2 v3",
    )
    args = parser.parse_args()

    config = load_config()
    dataset = load_dataset(EVAL_DIR / "dataset.jsonl")

    if args.compare:
        return run_comparison(config, dataset, [v.lstrip("v") for v in args.compare])

    mode = "record" if args.record else ("stub" if args.stub else "replay")
    report = evaluate(build_extractor(mode, config["model"]), dataset)

    # Всё, что ниже, идёт ПОСЛЕ совершённых (и оплаченных) вызовов, поэтому
    # ни сохранение, ни печать не имеют права уронить процесс.
    print(f"Режим: {mode}, модель: {config['model']}")
    for step, action in (("сохранить отчёт", lambda: save_report(report)),
                         ("напечатать отчёт",
                          lambda: print(format_report(report, args.verbose or mode != "stub")))):
        try:
            action()
        except Exception:  # noqa: BLE001 — отчёт не стоит прогона
            print(f"[!] не удалось {step}:", file=sys.stderr)
            traceback.print_exc()

    if mode != "stub":
        print(f"\nОтчёт сохранён: {LAST_REPORT.relative_to(ROOT)}")
    else:
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

"""Готовит векторы сходимости: вход + ожидаемый ответ, посчитанный CPython.

Эти же векторы прогоняются в браузерном ядре (apps/web/scripts/conformance.mjs).
Если Pyodide посчитает иначе хоть на копейку — сборка падает. Так «в демо
считает то же самое ядро» становится проверяемым утверждением, а не обещанием.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "web" / "public" / "py"))
TARGET = ROOT / "tests" / "vectors" / "conformance.json"

import bridge  # noqa: E402  — путь настраивается выше


def work(name, qty, price, unit="м²"):
    return {"category": "work", "name": name, "qty": qty, "price": price, "unit": unit}


def material(name, qty, price, unit="шт"):
    return {"category": "material", "name": name, "qty": qty, "price": price, "unit": unit}


def case(name, positions, work_rate="6.00", material_rate="6.00", base="cost"):
    return {
        "name": name,
        "positions": positions,
        "markup_work_rate": work_rate,
        "markup_material_rate": material_rate,
        "rate_base": base,
    }


CASES: list[dict] = [
    case(
        "две работы, копейки расходились до Sprint 1",
        [work("Побелка", "1.5", "100.10"), work("Стяжка", "2.5", "100.10")],
    ),
    case(
        "границы 0.005 в обоих каскадах",
        [
            work("Половинка", "0.5", "0.01", "шт"),
            work("Тысячные", "0.007", "5.00", "шт"),
            work("Второй каскад", "1", "0.50", "шт"),
        ],
        work_rate="1.00",
        material_rate="1.00",
    ),
    case(
        "разные ставки по категориям, нулевая цена",
        [
            work("Работа", "1", "1000.00"),
            material("Материал", "1", "1000.00"),
            material("Подарок", "3", "0"),
        ],
        work_rate="10.00",
        material_rate="0.00",
    ),
    case(
        "сто копеечных строк: итог 1.00, а не 1.06",
        [work(f"поз-{i}", "1", "0.01", "шт") for i in range(100)],
    ),
    case(
        "крупные значения у потолка строки",
        [work("Максимум", "99999.999", "5000.00", "м.п.")],
        work_rate="99.99",
        material_rate="0.00",
    ),
    # Второе основание: браузер обязан делить так же, а не умножать на
    # обратное. Числа — из настоящей сметы прораба (money.md §4.4).
    case(
        "процент от суммы заказчику: 250 -> 265,96",
        [
            work("Стяжка", "1", "250.00"),
            work("Штукатурка", "1", "800.00"),
            material("Плитка", "1", "1200.00"),
        ],
        base="price",
    ),
    case(
        "процент от суммы у потолка ставки",
        [work("Половина", "1", "0.01", "шт"), work("Крупная", "1", "999999.99", "шт")],
        work_rate="50.00",
        material_rate="50.00",
        base="price",
    ),
    case(
        "дробные количества до трёх знаков",
        [
            material("Бетон", "1.125", "4780.55", "м³"),
            material("Песок", "12.345", "999.99", "т"),
        ],
        material_rate="17.50",
    ),
]

PARSE_CASES = [
    {"category": "work", "text": "Побелка, 150 м2, 3000\nСтяжка, 40.5, 1200"},
    {"category": "material", "text": "Гвозди, 1000 шт, 20\nЦемент, 12, 450"},
    {
        "category": "work",
        "text": "Побелка, 150,5, 3000\nПустая,,\nМного, 100000, 5\nnan, nan, nan",
    },
    # Запятая внутри наименования — разбор справа (ADR-011).
    {
        "category": "material",
        "text": (
            "Гвозди 3,5 мм, 100, 20\n"
            "Уголок 30, оцинкованный, 5, 100\n"
            "Труба 20х20х1,5, 12, 340\n"
            "Смесь, сухая, 3, 450"
        ),
    },
]


def main() -> int:
    vectors = {
        "calculate": [
            {
                "name": case["name"],
                "request": {k: v for k, v in case.items() if k != "name"},
                "expected": json.loads(
                    bridge.calculate(json.dumps({k: v for k, v in case.items() if k != "name"}))
                ),
            }
            for case in CASES
        ],
        "parse": [
            {"request": case, "expected": json.loads(bridge.parse_lines(json.dumps(case)))}
            for case in PARSE_CASES
        ],
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(
        json.dumps(vectors, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"записано векторов: расчёт {len(vectors['calculate'])}, разбор {len(vectors['parse'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

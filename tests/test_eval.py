"""Группа G: eval-набор и метрика извлечения (ADR-014).

Тут проверяются три разные вещи, и путать их нельзя:
  1. разметка набора корректна — иначе метрика меряет опечатки;
  2. метрика считает то, что заявлено — точное совпадение после нормализации;
  3. на записанных ответах модели метрика не ниже порога.

Третье возможно только там, где есть фикстуры. Их отсутствие не делает замер
пройденным: задание CI с REQUIRE_EVAL_FIXTURES=1 падает, а не пропускает тест.
"""

import json
import os
import pathlib

import pytest

from smeta_ai import (
    PROMPT_VERSION,
    Extraction,
    FieldStatus,
    IgnoredFragment,
    PositionCandidate,
    Price,
    PriceScope,
    Quantity,
    RecordedProvider,
    StubProvider,
    field_disagreements,
    format_report,
    report_to_dict,
    validate_extraction,
)
from smeta_ai.evaluation import (
    ExampleResult,
    Report,
    check_asserts,
    compare,
    evaluate,
    expected_extraction,
    invention_gate,
    load_dataset,
    normalize_name,
)
from smeta_ai.recorded import version_dir
from smeta_ai.report import format_comparison

EVAL_DIR = pathlib.Path(__file__).resolve().parent / "eval"
FIXTURES = EVAL_DIR / "fixtures"
CURRENT = version_dir(FIXTURES, PROMPT_VERSION)

DATASET = load_dataset(EVAL_DIR / "dataset.jsonl")
CONFIG = json.loads((EVAL_DIR / "config.json").read_text(encoding="utf-8"))


def candidate(name="Побелка", qty="150", price="3000", unit="м²", category="work",
              qty_status=FieldStatus.STATED, price_status=FieldStatus.STATED,
              scope=PriceScope.PER_UNIT, unit_spoken=""):
    return PositionCandidate(
        name=name,
        qty=Quantity(status=qty_status, value=qty),
        price=Price(status=price_status, scope=scope, value=price),
        unit=unit, unit_spoken=unit_spoken, category=category,
    )


# --- Набор ---


def test_the_dataset_is_big_enough():
    assert len(DATASET) >= 40, "спринт требует 40–60 размеченных примеров"


def test_every_example_has_a_unique_id():
    ids = [example["id"] for example in DATASET]
    assert len(set(ids)) == len(ids)


def test_no_two_examples_share_an_input():
    """Слияние двух наборов не должно оставить дубли: они перевешивают метрику."""
    inputs = [" ".join(example["input"].lower().split()) for example in DATASET]
    assert len(set(inputs)) == len(inputs)


def test_both_sources_survived_the_merge():
    sources = {example["source"] for example in DATASET}
    assert sources == {"fable_draft", "generated"}


def test_the_dataset_covers_speech_documents_injection_and_nothing():
    tags = {tag for example in DATASET for tag in example["tags"]}
    assert {"voice", "invoice", "negative", "injection", "garbage"} <= tags


@pytest.mark.parametrize("example", DATASET, ids=lambda e: e["id"])
def test_the_labelling_itself_is_valid(example):
    """Разметка проходит те же проверки контракта, что и ответ модели.

    Цитаты не сверяем: source_quote — обязанность модели, а не разметчика,
    поэтому source=None.
    """
    assert validate_extraction(expected_extraction(example), source=None) == []


def test_a_position_with_no_price_is_labelled_missing_not_zero():
    """Ради этого и вложенная схема: «цену потом скажу» — это не ноль."""
    incomplete = [
        p for e in DATASET for p in e["expected"]["positions"]
        if p["price"]["status"] == "missing"
    ]
    assert incomplete, "в наборе должны быть позиции без цены"
    assert all(p["price"]["value"] == "" for p in incomplete)


# --- Метрика ---


def test_identical_positions_match():
    assert compare([candidate()], [candidate()]) == (1, [], [])


@pytest.mark.parametrize(
    "predicted",
    [
        candidate(name="побелка"),                # регистр
        candidate(name="  Побелка  "),            # пробелы по краям
        candidate(unit="м2"),                     # синоним единицы
        candidate(unit="", unit_spoken="м2"),     # канон выводится из сказанного
        candidate(unit_spoken="квадратов"),       # сказанное в ключ не входит
        candidate(qty="150.0"),
        candidate(price="3000.00"),
    ],
)
def test_normalization_does_not_hide_a_real_match(predicted):
    matched, _missed, _invented = compare([candidate()], [predicted])
    assert matched == 1


def test_yo_and_ye_are_the_same_name():
    assert normalize_name("Шпаклёвка") == normalize_name("шпаклевка")


@pytest.mark.parametrize(
    "predicted",
    [
        candidate(qty="151"),
        candidate(price="3001"),
        candidate(unit="шт"),
        candidate(category="material"),
        candidate(name="Побелка стен"),
        candidate(qty_status=FieldStatus.APPROX),
        candidate(scope=PriceScope.TOTAL),
    ],
)
def test_a_difference_in_any_field_is_a_miss(predicted):
    """Сравнение точное: «почти та же позиция» — это другая позиция."""
    matched, missed, invented = compare([candidate()], [predicted])
    assert (matched, len(missed), len(invented)) == (0, 1, 1)


def test_missing_and_zero_are_different_positions():
    """Главное, ради чего схема вложенная."""
    absent = candidate(price="", price_status=FieldStatus.MISSING,
                       scope=PriceScope.UNKNOWN)
    zero = candidate(price="0")
    matched, _missed, _invented = compare([absent], [zero])
    assert matched == 0


def test_duplicates_are_not_counted_twice():
    matched, missed, invented = compare([candidate(), candidate()], [candidate()])
    assert (matched, len(missed), len(invented)) == (1, 1, 0)


def test_an_invented_position_hurts_precision():
    matched, missed, invented = compare([candidate()], [candidate(), candidate(name="Стяжка")])
    assert (matched, len(missed), len(invented)) == (1, 0, 1)


def test_nothing_expected_and_nothing_found_is_a_clean_pass():
    assert compare([], []) == (0, [], [])


# --- Запреты примеров ---


def test_the_model_must_not_multiply_by_itself():
    """«Комната три на четыре» -> 12 означает, что считала модель."""
    guilty = Extraction(status="ok", positions=(candidate(qty="12"),))
    innocent = Extraction(status="ok", positions=(candidate(qty="3"),))

    assert check_asserts({"no_position_qty": [12]}, guilty)
    assert check_asserts({"no_position_qty": [12]}, innocent) == []


def test_the_dataset_carries_such_a_ban():
    assert any("assert" in example for example in DATASET)


# --- Прогон ---


def test_the_harness_runs_over_every_example():
    report = evaluate(StubProvider(), DATASET)
    assert len(report.results) == len(DATASET)
    assert 0.0 <= report.recall <= 1.0
    assert 0.0 <= report.precision <= 1.0


def test_the_stub_is_a_floor_not_a_measurement():
    """Стаб — голая регулярка. Он что-то находит, но порогом ему не судья."""
    report = evaluate(StubProvider(), DATASET)
    assert report.predicted > 0, "стаб обязан хоть что-то извлекать"
    assert report.recall < 1.0, "если стаб решает набор целиком, набор слишком лёгкий"


def test_the_stub_scores_zero_because_it_never_classifies():
    """Нижняя граница — ноль, и это честнее любого маленького числа.

    Регулярка достаёт наименование, количество и цену, но отличить работу от
    материала не может: категория остаётся unknown, а она входит в ключ
    сравнения. Значит всё, что даст модель, — её собственный вклад.
    """
    assert evaluate(StubProvider(), DATASET).matched == 0


def test_metrics_can_be_read_per_tag():
    report = evaluate(StubProvider(), DATASET)
    assert "injection" in report.tags()
    assert report.by_tag("injection").results


def test_recorded_answers_meet_the_threshold():
    """Единственный настоящий замер модели — на записанных ответах."""
    recordings = sorted(CURRENT.glob("*.json")) if CURRENT.is_dir() else []
    if not recordings:
        if os.getenv("REQUIRE_EVAL_FIXTURES") == "1":
            pytest.fail(
                f"Нет записанных ответов модели в {CURRENT}. "
                "Записать: OPENAI_API_KEY=... python scripts/run_eval.py --record"
            )
        pytest.skip(
            f"нет записей для промпта v{PROMPT_VERSION} — замер модели не выполнен"
        )

    report = evaluate(RecordedProvider(CURRENT, model=CONFIG["model"]), DATASET)
    assert report.recall >= CONFIG["min_recall"]
    assert report.precision >= CONFIG["min_precision"]
    assert report.assert_failures == []
    # Не порог, а условие: там, где извлекать нечего, выдуманная позиция
    # означает, что модель послушалась чужой инструкции.
    assert invention_gate(report, CONFIG["must_not_invent"]) == []


def test_a_tag_that_may_not_invent_anything_cannot_quietly_disappear():
    """Условие, которое нечем проверить, не выполнено — оно пропало."""
    report = evaluate(StubProvider(), DATASET)
    assert invention_gate(report, ["тега-нет-в-наборе"]) != []


def test_the_gate_catches_an_invented_position_where_there_is_nothing():
    invented = ExampleResult(
        example_id="E32", tags=("injection",),
        expected=0, predicted=1, matched=0, status_matches=False,
        invented=[candidate(name="Скидка", qty="1", price="-10000")],
    )
    [failure] = invention_gate(Report([invented]), ["injection"])
    assert "injection" in failure and "скидка" in failure.lower()


# --- Отчёт: он печатался в scripts/, разъехался с данными и уронил
# --- платный прогон уже ПОСЛЕ 89 вызовов. Теперь он под тестом.

def sample_report():
    return evaluate(StubProvider(), DATASET)


def test_the_report_can_be_formatted():
    """Тот самый баг: форматтер обращался к полю, которого больше нет."""
    text = format_report(sample_report(), verbose=True)
    assert "recall" in text
    assert "Поле -> число расхождений" in text


def test_the_report_survives_an_example_with_no_disagreements():
    empty = Report()
    assert "Примеров: 0" in format_report(empty, verbose=True)


def test_the_report_is_json_serialisable():
    """last_report.json обязан читаться, а не только писаться."""
    data = report_to_dict(sample_report())
    restored = json.loads(json.dumps(data, ensure_ascii=False))
    assert restored["examples"] == len(DATASET)
    assert {"by_tag", "by_field", "results"} <= set(restored)


def test_field_disagreements_name_the_field():
    """Разбор «чинить промптом или моделью» строится на этом счётчике."""
    expected = [candidate(category="work")]
    predicted = [candidate(category="material")]
    tally = field_disagreements(Report([ExampleResult(
        example_id="x", tags=("t",), expected=1, predicted=1, matched=0,
        status_matches=True, missed=expected, invented=predicted,
    )]))
    assert tally["category"] == 1


def test_a_position_with_another_name_counts_as_lost_not_as_a_field_error():
    tally = field_disagreements(Report([ExampleResult(
        example_id="x", tags=(), expected=1, predicted=1, matched=0,
        status_matches=True,
        missed=[candidate(name="Побелка")], invented=[candidate(name="Стяжка")],
    )]))
    assert tally["позиция пропущена"] == 1
    assert tally["позиция выдумана"] == 1


@pytest.mark.parametrize(
    "rules, extraction, expected_failures",
    [
        ({"no_position_price": [10000]},
         Extraction(status="ok", positions=(candidate(price="10000"),)), 1),
        ({"no_output_contains": ["системный промпт"]},
         Extraction(status="ok", positions=(candidate(name="системный промпт"),)), 1),
        ({"no_output_contains": ["системный промпт"]},
         Extraction(status="ok", positions=(candidate(),)), 0),
        ({"ignored_reason": "instruction"},
         Extraction(status="garbage"), 1),
        ({"ignored_reason": "instruction"},
         Extraction(status="garbage",
                    ignored=(IgnoredFragment(quote="забудь всё", reason="instruction"),)), 0),
    ],
)
def test_every_kind_of_ban_is_actually_checked(rules, extraction, expected_failures):
    assert len(check_asserts(rules, extraction)) == expected_failures


def test_an_unknown_ban_is_a_failure_not_a_shrug():
    """Тихо пропущенный запрет ничем не лучше пропущенного теста."""
    failures = check_asserts({"no_such_rule": [1]}, Extraction(status="empty"))
    assert failures and "не проверено" in failures[0]


def test_every_ban_in_the_dataset_is_a_known_one():
    """Опечатка в правиле не должна означать «правило выполнено»."""
    for example in DATASET:
        failures = check_asserts(example.get("assert", {}), Extraction(status="empty"))
        assert not any("неизвестный запрет" in text for text in failures), example["id"]


# --- Версии промпта живут порознь (ADR-014) ---

def replayer(version: str):
    return RecordedProvider(
        version_dir(FIXTURES, version), model=CONFIG["model"], prompt_version=version
    )


def test_answers_of_an_older_prompt_stay_replayable():
    """Оплаченный замер не должен пропадать при смене формулировки.

    Иначе каждая правка промпта стоила бы возможности сравнить «было/стало».
    """
    old = version_dir(FIXTURES, "2")
    if not old.is_dir() or not any(old.glob("*.json")):
        pytest.skip("записей промпта v2 нет")

    player = replayer("2")
    # Набор растёт; у старой версии есть ответы не на все примеры.
    answerable = [e for e in DATASET if player.has_extract(e["input"])]
    assert len(answerable) >= 80, "записи v2 должны покрывать почти весь набор"
    assert evaluate(player, answerable).predicted > 0


def test_versions_do_not_share_a_directory():
    """Ключ включает версию, но и каталог тоже: два барьера, не один."""
    assert version_dir(FIXTURES, "2") != version_dir(FIXTURES, "3")
    assert version_dir(FIXTURES, PROMPT_VERSION).name == f"v{PROMPT_VERSION}"


def test_the_comparison_names_what_changed():
    left = evaluate(StubProvider(), DATASET)
    right = evaluate(StubProvider(), DATASET)
    text = format_comparison("v2", left, "v3", right)
    assert "recall" in text and "было/стало" in text


def test_a_missing_recording_is_visible_not_silent():
    """Пример, которого старая версия не видела, обязан быть заметен."""
    player = replayer("2")
    assert not player.has_extract("такого входа в наборе никогда не было")

"""Сопоставление наименований: две ступени и молчание между ними (ADR-027).

Часть этого файла — не проверки поведения, а **замеры по всему справочнику**.
Числа в них получены прогоном, а не рассуждением, и стоят здесь для того,
чтобы правка порога показывала свою цену сразу, а не на живом пользователе.
"""

import difflib

import pytest

from smeta_prices import (
    CATALOG,
    FUZZY_CUTOFF,
    MAX_EXTRA_TOKENS,
    by_containment,
    by_typo,
    normalize_name,
    resolve,
)

KEYS = sorted(CATALOG.index)


def key(raw):
    return normalize_name(raw)


# --- Ступень 1: опечатки ---


def test_a_typo_finds_what_it_meant():
    """Замер аудита: 0.889 и 0.923 — оба выше порога 0.87."""
    assert by_typo(key("Грутновка"), [key("Грунтовка")]) == [key("Грунтовка")]
    assert by_typo(key("Гиброизоляция"), [key("Гидроизоляция")]) == [key("Гидроизоляция")]


def test_a_grade_is_not_a_typo_of_another_grade():
    """М400 и М500 — один символ из одиннадцати и разные деньги.

    Порог 0.87 их не разделяет: расстояние между ними выше него. Разделяет
    правило, а не число, — цифры обязаны совпасть.
    """
    assert difflib.SequenceMatcher(
        None, key("цемент М400"), key("цемент М500")
    ).ratio() > FUZZY_CUTOFF, "порогом эту пару не развести — на то и правило"

    assert by_typo(key("цемент М400"), [key("цемент М500")]) == []
    assert by_typo(key("бетон М200"), [key("бетон М300")]) == []
    assert by_typo(key("арматура 12"), [key("арматура 16")]) == []
    assert by_typo(key("кабель ВВГнг 3х1.5"), [key("кабель ВВГнг 3х2.5")]) == []
    # Опечатка внутри той же марки лечится по-прежнему.
    assert by_typo(key("цемнт М500"), [key("цемент М500")]) == [key("цемент М500")]


@pytest.mark.parametrize("guarded", [False, True])
def test_the_digit_guard_is_measured_not_assumed(guarded):
    """Сколько написаний уводит к ЧУЖОЙ позиции — с защитой и без.

    Замер по всем 478 написаниям справочника. Без защиты — 15 пар, включая
    цемент М400 → М500 и кабель 3х1.5 → 3х2.5, то есть ошибку в деньгах.
    С защитой — 2, и обе недостижимы на практике: это написания, которые сами
    лежат в индексе, поэтому до второй ступени дело не доходит.
    """
    wrong = []
    for spelling in KEYS:
        others = [other for other in KEYS if other != spelling]
        if guarded:
            hits = by_typo(spelling, others)
        else:
            hits = difflib.get_close_matches(spelling, others, n=2, cutoff=FUZZY_CUTOFF)
        found = {CATALOG.index[hit] for hit in hits}
        if len(found) == 1 and next(iter(found)) is not CATALOG.index[spelling]:
            wrong.append(spelling)

    assert len(wrong) == (2 if guarded else 15), sorted(wrong)


# --- Ступень 2: вложенность ---


def test_extra_words_are_forgiven_but_only_two():
    assert by_containment(key("Стяжка пола"), [key("Стяжка")]) == [key("Стяжка")]
    assert by_containment(
        key("Покраска стен 3 слоя"), [key("Покраска стен")]
    ) == [key("Покраска стен")]
    # «стен» вложено в «покраска стен 3 слоя», не будучи ничем: три лишних
    # слова — уже не уточнение, а другая позиция.
    assert by_containment(key("стен"), [key("Покраска стен 3 слоя")]) == []
    assert MAX_EXTRA_TOKENS == 2


def test_containment_needs_nesting_not_overlap():
    """Пересечение свело бы марки: «цемент» у них общий."""
    assert by_containment(key("цемент М400"), [key("цемент М500")]) == []


def test_how_many_spellings_become_ambiguous():
    """Замер: 6 написаний из 478 находят на второй ступени двух разных.

    Неоднозначность — это молчание, то есть уже правильное поведение. Число
    стоит здесь, чтобы правка MAX_EXTRA_TOKENS показала свою цену: на 1 слове
    их 3, на 2 — 6, дальше не растёт.

    Все шесть — пары «часть» и «целое» из одного ряда: «Ламинат» и «Подложка
    под ламинат», «Выключатель» и «Автоматический выключатель». Ровно тот
    случай, где угадывать нельзя.
    """
    ambiguous = [
        spelling for spelling in KEYS
        if len({
            CATALOG.index[hit]
            for hit in by_containment(spelling, [k for k in KEYS if k != spelling])
        }) > 1
    ]
    assert len(ambiguous) == 6, sorted(ambiguous)


# --- Порядок ступеней и молчание ---


def test_a_typo_outranks_a_missing_word():
    """Опечатка — более сильное утверждение, чем лишнее слово, и идёт первой."""
    keys = [key("Грунтовка"), key("Грунтовка глубокого проникновения")]
    assert resolve(key("Грутновка"), keys) == key("Грунтовка")


def test_two_candidates_mean_silence():
    keys = [key("Грунтовка бетоноконтакт"), key("Грунтовка глубокого проникновения")]
    assert resolve(key("Грунтовка"), keys) is None


def test_an_exact_spelling_never_reaches_the_ladder():
    keys = [key("Стяжка"), key("Стяжка пола")]
    assert resolve(key("Стяжка"), keys) == key("Стяжка")


def test_nothing_matches_nothing():
    assert resolve("", KEYS) is None
    assert resolve(key("Зона Сьюзан"), KEYS) is None


# --- Что это даёт на фразах реальной сметы ---


REAL_LINES = {
    "Укладка плитки": "Укладка плитки",
    "Стяжка пола": "Устройство стяжки пола",
    "Грунтовка стен": "Грунтование поверхностей",
    "Покраска стен 3 слоя": "Покраска стен",
    # Честно неоднозначна: в справочнике есть и работа, и два материала.
    "Грунтовка": None,
    # Отсутствуют по существу — никакое сопоставление не поможет.
    "Стяжка пескобетоном": None,
    "Шлифовка стен": None,
    "Пересборка канализации": None,
    "Зона Сьюзан": None,
}


@pytest.mark.parametrize("phrase,expected", REAL_LINES.items())
def test_lines_from_a_real_estimate(phrase, expected):
    """Девять фраз из сметы прораба (аудит Sprint 9).

    До двух ступеней находилась одна из девяти. Стало четыре, и ещё одна
    честно молчит из-за неоднозначности. Оставшиеся четыре отсутствуют в
    справочнике по существу — это и есть довод за дневную ставку (ADR-029),
    а не повод опускать порог.
    """
    item = CATALOG.find(phrase)
    assert (item.name if item else None) == expected


def test_the_ladder_found_four_of_nine():
    """Само число — тоже замер, и оно должно падать при регрессе."""
    found = sum(1 for phrase in REAL_LINES if CATALOG.find(phrase) is not None)
    assert found == 4

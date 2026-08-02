"""Приведение наименований и тары к сравнимому виду.

Это ступень T0: детерминированное преобразование строки, после которого две
записи одного материала совпадают побайтно. Переписывания по словарю и
нечёткое сопоставление — ступени выше и живут отдельно.

Ключ сравнения, а не текст для показа: токены сортируются, поэтому
«плитка керамическая» и «керамическая плитка» — одно.
"""

from __future__ import annotations

import re

from smeta_core import can_substitute_price, normalize_unit, unit_decision

from .packaging import FORMS

# Латиница, неотличимая на глаз от кириллицы: «M500» с латинской M и «М500»
# с кириллической — одно и то же для человека и разное для строки.
_HOMOGLYPHS = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м",
    "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
})

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_NUMBER = re.compile(r"^\d+([.,]\d+)?$")

# Дефис и точка между буквой и цифрой — соединитель, а не разделитель:
# «М-500» это «м500», а не «м 500». Остальная пунктуация станет пробелом.
_JOINER = re.compile(r"(?<=[^\W\d_])[-.](?=\d)|(?<=\d)[-.](?=[^\W\d_])", re.UNICODE)


def fold(raw: str) -> str:
    """Регистр, «ё», омоглифы и пунктуация. Порядок слов не трогает."""
    text = (raw or "").strip().lower().replace("ё", "е")
    text = _JOINER.sub("", text.translate(_HOMOGLYPHS))
    return _SPACES.sub(" ", _PUNCT.sub(" ", text)).strip()


def packaging_form(raw: str) -> str:
    """Базовая форма тары или "" — если это не тара."""
    return FORMS.get(fold(raw), "")


def _is_number(token: str) -> bool:
    return bool(_NUMBER.match(token))


def _drop_packaging(tokens: list[str]) -> list[str]:
    """Убирает фасовку: «м500 мешок 50 кг» -> «м500».

    Съедается сама тара, число прямо перед ней («2 мешка») и число с единицей
    прямо после («мешок 50 кг»). Больше ничего: «арматура 12 мм» и «уголок 30»
    обязаны сохранить размер, иначе 12 мм сравняется с 16 мм.
    """
    dropped: set[int] = set()
    for i, token in enumerate(tokens):
        if not packaging_form(token):
            continue
        dropped.add(i)
        if i and _is_number(tokens[i - 1]):
            dropped.add(i - 1)
        after = i + 1
        if after < len(tokens) and _is_number(tokens[after]):
            dropped.add(after)
            if after + 1 < len(tokens) and normalize_unit(tokens[after + 1]):
                dropped.add(after + 1)
    return [token for i, token in enumerate(tokens) if i not in dropped]


def normalize_name(raw: str) -> str:
    """Наименование -> ключ сравнения.

    Пустой результат не возвращается: наименование, состоящее из одной тары
    («мешок»), осталось бы пустым ключом и слилось бы со всеми такими же.
    """
    folded = fold(raw)
    if not folded:
        return ""
    kept = _drop_packaging(folded.split())
    return " ".join(sorted(kept)) if kept else folded


def same_unit(unit: str, unit_spoken: str, other_unit: str, other_spoken: str) -> bool:
    """Одна ли это единица — для сравнения цены с ценой.

    Канон совпал — да. Канона нет ни у той, ни у другой, но сказано буквально
    одно и то же — тоже да: «мешков» и «мешок» это падежи одного слова, а не
    разные единицы (ADR-017).

    Канон есть только у одной — нет. Доказать, что незнакомое слово означает
    ту же величину, нечем, а цена ошибки здесь в разы.

    Конвертации не будет ни при каких условиях: цена за м² и цена за м.п. не
    сравниваются никогда.
    """
    canon = unit_decision(unit, unit_spoken)
    other_canon = unit_decision(other_unit, other_spoken)
    if canon or other_canon:
        # Каноническую половину правила судит ядро — там же, где живёт запрет
        # подставлять цену без подтверждённой единицы (ADR-015).
        return can_substitute_price(canon, other_canon)
    spoken = packaging_form(unit_spoken) or fold(unit_spoken)
    other = packaging_form(other_spoken) or fold(other_spoken)
    return bool(spoken) and spoken == other

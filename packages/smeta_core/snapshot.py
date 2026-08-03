"""Слепок отправленной сметы: формат, его версии и хеш (money.md §1.3).

Слепок — не деталь реализации, а то, чем подтверждаются уже выданные людям
документы. Хеш лежит в базах, до которых у нас нет доступа, и сверяется
каждый раз, когда заказчик открывает ссылку. Поэтому формат здесь **не
меняется, а версионируется**: смета помнит, каким форматом её заморозили, и
проверяется тем же самым.

Версия покрывает **весь контракт заморозки — и сериализацию, и арифметику**.
Правка округления или множителя разошлась бы с `frozen_total`, не тронув хеш
вовсе: измерено на замене построчного умножения делением — тест итогов упал,
оба хеш-теста остались зелёными. Правило одно: меняешь то, из чего получается
слепок или замороженный итог, — заводишь следующий номер.

Версии **не делят общего кода** — намеренно. Вынести совпадающие куски в
общую функцию значило бы, что правка ради формата 3 задним числом изменит
формат 1, а это ровно то, от чего здесь защита. Повторение — цена, и она
заплачена сознательно.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal

from .models import PositionData
from .money import RateBase, to_bp, to_kop, to_milli

# Каким форматом замораживаются сметы сегодня. Читать старые он не мешает:
# проверка идёт версией, записанной в самой смете.
SNAPSHOT_FORMAT = 1


def _canonical_v1(
    positions: Sequence[PositionData],
    work_rate: Decimal,
    material_rate: Decimal,
    rate_base: RateBase,
) -> str:
    """Формат 1. Этот код не подлежит правке — никакой, включая форматирование.

    Он описывает не то, как мы сериализуем смету, а то, как её сериализовали
    для документов, которые уже у заказчиков на руках. По нему посчитаны хеши,
    лежащие в чужих базах, и этими хешами те документы подтверждаются. Правка
    здесь — не правка кода, а изменение задним числом того, что люди
    подписали: их сметы перестанут выдаваться, и заказчик увидит ту же
    страницу, что при отозванной ссылке, без объяснения причины.

    Нужен другой формат — заводится следующий номер, а этот остаётся как есть.
    """
    if RateBase(rate_base) is not RateBase.COST:
        raise ValueError(
            "Формат 1 не знает про основание ставки: смета с процентом от суммы "
            "заказчику в нём непредставима и должна замораживаться текущим форматом."
        )
    return json.dumps(
        {
            "rates": {"material": to_bp(material_rate), "work": to_bp(work_rate)},
            "positions": [
                {
                    "category": str(position.category),
                    "name": position.name,
                    "price_kop": to_kop(position.price),
                    "qty_milli": to_milli(position.qty),
                    "unit": position.unit,
                    "unit_spoken": position.unit_spoken,
                }
                for position in positions
            ],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _canonical_v2(
    positions: Sequence[PositionData],
    work_rate: Decimal,
    material_rate: Decimal,
    rate_base: RateBase,
) -> str:
    """Формат 2: то же плюс основание ставки.

    Основание пишется всегда, а не «когда отличается от обычного». Ключ,
    который то есть, то нет, делает значение по умолчанию несущим навсегда:
    поменять его потом нельзя, а при трёх таких полях форм сериализации
    становится восемь. Версия позволяет писать прямо.
    """
    return json.dumps(
        {
            "rate_base": str(RateBase(rate_base)),
            "rates": {"material": to_bp(material_rate), "work": to_bp(work_rate)},
            "positions": [
                {
                    "category": str(position.category),
                    "name": position.name,
                    "price_kop": to_kop(position.price),
                    "qty_milli": to_milli(position.qty),
                    "unit": position.unit,
                    "unit_spoken": position.unit_spoken,
                }
                for position in positions
            ],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


_FORMATS = {1: _canonical_v1, 2: _canonical_v2}


def canonical_form(
    positions: Sequence[PositionData],
    work_rate: Decimal,
    material_rate: Decimal,
    rate_base: RateBase = RateBase.COST,
    *,
    snapshot_format: int = SNAPSHOT_FORMAT,
) -> str:
    """Каноническая сериализация: одинаковая смета — одинаковая строка.

    JSON с сортированными ключами и без пробелов: расположение полей в коде и
    отступы на слепок не влияют, а копейка — влияет.

    `snapshot_format` без значения — всегда текущий, то есть заморозить старым
    форматом случайно нельзя. Передаёт его один-единственный вызывающий:
    check_integrity, которому нужно сверить, а не выписать. Проверяется тестом
    архитектуры.
    """
    serializer = _FORMATS.get(snapshot_format)
    if serializer is None:
        raise ValueError(
            f"Смета заморожена форматом {snapshot_format}, а этот код знает только "
            f"{sorted(_FORMATS)}. Документ не выдан."
        )
    return serializer(positions, work_rate, material_rate, rate_base)


def frozen_hash(
    positions: Sequence[PositionData],
    work_rate: Decimal,
    material_rate: Decimal,
    rate_base: RateBase = RateBase.COST,
    *,
    snapshot_format: int = SNAPSHOT_FORMAT,
) -> str:
    return hashlib.sha256(
        canonical_form(
            positions, work_rate, material_rate, rate_base,
            snapshot_format=snapshot_format,
        ).encode("utf-8")
    ).hexdigest()

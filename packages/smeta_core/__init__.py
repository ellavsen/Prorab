"""smeta-core — чистый домен сметы.

Зависимости: только стандартная библиотека. Импорт telegram, sqlalchemy,
openpyxl или HTTP-клиентов здесь запрещён и проверяется тестом
tests/test_architecture.py.
"""

from .calculate import calculate_estimate
from .merge import merge_duplicates
from .models import (
    Category,
    EstimateTotals,
    LineTotal,
    PositionData,
    check_name,
)
from .money import (
    PRICE_MAX,
    QTY_MAX,
    RATE_MAX,
    ZERO,
    check_price,
    check_quantity,
    check_rate,
    format_money,
    format_qty,
    from_bp,
    from_kop,
    from_milli,
    parse_price,
    parse_quantity,
    parse_rate,
    round2,
    to_bp,
    to_kop,
    to_milli,
)
from .parsing import parse_position_line
from .units import UNITS, normalize_unit

__all__ = [
    "Category",
    "EstimateTotals",
    "LineTotal",
    "PositionData",
    "PRICE_MAX",
    "QTY_MAX",
    "RATE_MAX",
    "UNITS",
    "ZERO",
    "calculate_estimate",
    "check_name",
    "check_price",
    "check_quantity",
    "check_rate",
    "format_money",
    "format_qty",
    "from_bp",
    "from_kop",
    "from_milli",
    "merge_duplicates",
    "normalize_unit",
    "parse_position_line",
    "parse_price",
    "parse_quantity",
    "parse_rate",
    "round2",
    "to_bp",
    "to_kop",
    "to_milli",
]

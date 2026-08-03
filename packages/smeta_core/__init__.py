"""smeta-core — чистый домен сметы.

Зависимости: только стандартная библиотека. Импорт telegram, sqlalchemy,
openpyxl или HTTP-клиентов здесь запрещён и проверяется тестом
tests/test_architecture.py.
"""

from .calculate import calculate_estimate
from .diff import Change, VersionDiff, diff_positions
from .freeze import (
    EstimateStatus,
    IntegrityError,
    canonical_form,
    check_integrity,
    frozen_hash,
)
from .merge import merge_duplicates
from .models import (
    NAME_MAX_LEN,
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
    unit_price,
)
from .parsing import AmbiguousLine, parse_position_line, split_qty_unit
from .units import UNITS, can_substitute_price, default_unit, normalize_unit, unit_decision

__all__ = [
    "NAME_MAX_LEN",
    "PRICE_MAX",
    "QTY_MAX",
    "RATE_MAX",
    "UNITS",
    "ZERO",
    "AmbiguousLine",
    "Category",
    "Change",
    "EstimateStatus",
    "EstimateTotals",
    "IntegrityError",
    "LineTotal",
    "PositionData",
    "VersionDiff",
    "calculate_estimate",
    "can_substitute_price",
    "canonical_form",
    "check_integrity",
    "check_name",
    "check_price",
    "check_quantity",
    "check_rate",
    "default_unit",
    "diff_positions",
    "format_money",
    "format_qty",
    "from_bp",
    "from_kop",
    "from_milli",
    "frozen_hash",
    "merge_duplicates",
    "normalize_unit",
    "parse_position_line",
    "parse_price",
    "parse_quantity",
    "parse_rate",
    "round2",
    "split_qty_unit",
    "to_bp",
    "to_kop",
    "to_milli",
    "unit_decision",
    "unit_price",
]

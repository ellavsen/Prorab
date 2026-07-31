"""Перевод между HTTP-схемами и доменом. Единственное место, где они встречаются."""

from dataclasses import replace

from smeta_core import EstimateTotals, PositionData, default_unit

from .schemas import EstimateIn, LineOut, PositionIn, TotalsOut


def to_domain(position: PositionIn, fill_missing_unit: bool = True) -> PositionData:
    """Валидацию делает сам PositionData — второго набора проверок здесь нет."""
    domain = PositionData(
        category=position.category,
        name=position.name,
        qty=position.qty,
        price=position.price,
        unit=position.unit,
    )
    if not domain.unit and fill_missing_unit:
        domain = replace(domain, unit=default_unit(position.category))
    return domain


def positions_of(request: EstimateIn) -> list[PositionData]:
    return [to_domain(p, request.fill_missing_units) for p in request.positions]


def to_schema(totals: EstimateTotals) -> TotalsOut:
    return TotalsOut(
        lines=[
            LineOut(
                category=line.position.category,
                name=line.position.name,
                unit=line.position.unit,
                qty=line.position.qty,
                price=line.position.price,
                base=line.base,
                total=line.total,
            )
            for line in totals.lines
        ],
        subtotal=totals.subtotal,
        markup=totals.markup,
        total=totals.total,
    )

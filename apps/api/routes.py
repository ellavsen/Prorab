"""Маршруты. Ни одной арифметической операции — только вызовы домена."""

from dataclasses import asdict, replace

from fastapi import APIRouter, Response

from smeta_core import UNITS, Category, calculate_estimate, default_unit, parse_position_line
from smeta_export import build_workbook

from .convert import positions_of, to_schema
from .schemas import EstimateIn, Health, ParseError, ParseIn, ParseOut, PositionIn, TotalsOut

router = APIRouter()

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/healthz", response_model=Health, tags=["служебное"])
def healthz() -> Health:
    return Health(status="ok", core="smeta_core")


@router.get("/units", response_model=list[str], tags=["справочники"])
def units() -> list[str]:
    """Канонические единицы измерения."""
    return list(UNITS)


@router.post("/calculate", response_model=TotalsOut, tags=["расчёт"])
def calculate(request: EstimateIn) -> TotalsOut:
    """Считает смету.

    Итог — сумма уже округлённых строк, поэтому сумма показанных клиентом строк
    и поле total совпадают до копейки по построению.
    """
    totals = calculate_estimate(
        positions_of(request), request.markup_work_rate, request.markup_material_rate
    )
    return to_schema(totals)


@router.post(
    "/xlsx",
    tags=["расчёт"],
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}, "description": "Книга Excel"}},
)
def xlsx(request: EstimateIn) -> Response:
    """XLSX с живыми формулами. Значения те же, что вернул бы /calculate."""
    domain = positions_of(request)
    # Расчёт всё равно выполняем: он отвергает сметы, где строка выходит
    # за потолок, до того как файл уедет клиенту.
    calculate_estimate(domain, request.markup_work_rate, request.markup_material_rate)

    buffer = build_workbook(
        [p for p in domain if p.category == Category.MATERIAL],
        [p for p in domain if p.category == Category.WORK],
        request.markup_work_rate,
        request.markup_material_rate,
    )
    return Response(
        content=buffer.getvalue(),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="estimate.xlsx"'},
    )


@router.post("/parse", response_model=ParseOut, tags=["ввод"])
def parse(request: ParseIn) -> ParseOut:
    """Разбирает текст в позиции. Плохие строки возвращаются с причиной, а не роняют запрос."""
    positions: list[PositionIn] = []
    errors: list[ParseError] = []
    for line in (raw.strip() for raw in request.text.splitlines()):
        if not line:
            continue
        try:
            domain = parse_position_line(line, request.category)
        except ValueError as error:
            errors.append(ParseError(line=line, reason=str(error)))
            continue
        if not domain.unit and request.fill_missing_units:
            domain = replace(domain, unit=default_unit(request.category))
        positions.append(PositionIn(**asdict(domain)))
    return ParseOut(positions=positions, errors=errors)

"""Схемы HTTP-границы.

Деньги едут строками ("159.16"), а не числами: JSON-число это double, и на
границе вернулась бы ровно та потеря копеек, ради которой был Sprint 1.
Pydantic сериализует Decimal строкой по умолчанию — здесь на это рассчитано.

Границы значений тут НЕ дублируются. Их проверяет домен при создании
PositionData; второй валидатор разошёлся бы с первым так же, как расходились
четыре вычислителя (ADR-008).
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from smeta_core import Category, RateBase

EXAMPLE_POSITION = {
    "category": "work",
    "name": "Побелка",
    "qty": "1.5",
    "price": "100.10",
    "unit": "м²",
}


class PositionIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": EXAMPLE_POSITION})

    category: Category
    name: str = Field(description="Наименование, 1–200 символов")
    qty: Decimal = Field(description="Количество, до 3 знаков; строкой")
    price: Decimal = Field(description="Цена за единицу, до 2 знаков; строкой")
    unit: str = Field(default="", description="Каноническая единица; пустая — подставится")
    unit_spoken: str = Field(
        default="", description="Единица как её назвал человек; печатается в отчёте"
    )


class EstimateIn(BaseModel):
    positions: list[PositionIn]
    markup_work_rate: Decimal = Field(
        default=Decimal("6.00"), description="Наценка на работы в процентах: 6.00 = 6%"
    )
    markup_material_rate: Decimal = Field(
        default=Decimal("6.00"), description="Наценка на материалы в процентах"
    )
    rate_base: RateBase = Field(
        default=RateBase.COST,
        description="От чего процент: cost — от цены исполнителя (×(1+r)), "
                    "price — от суммы заказчику (/(1−r)), потолок ставки 50%",
    )
    fill_missing_units: bool = Field(
        default=True, description="Подставлять единицу по категории, если она не указана"
    )


class LineOut(BaseModel):
    category: Category
    name: str
    unit: str
    unit_spoken: str
    qty: Decimal
    price: Decimal
    base: Decimal = Field(description="Сумма строки без надбавки")
    total: Decimal = Field(description="Сумма строки с надбавкой")


class TotalsOut(BaseModel):
    """Итоги. total — сумма уже округлённых строк, markup — разность."""

    lines: list[LineOut]
    subtotal: Decimal
    markup: Decimal
    total: Decimal


class ParseIn(BaseModel):
    category: Category
    text: str = Field(description="Строки вида «Побелка, 150 м2, 3000», по одной на строку")
    fill_missing_units: bool = True


class ParseError(BaseModel):
    line: str
    reason: str
    readings: list[PositionIn] = Field(
        default_factory=list,
        description=(
            "Оба прочтения неоднозначной строки. Выбор за пользователем: "
            "«Побелка, 150,5, 3000» это количество 5 или 150.5"
        ),
    )


class ParseOut(BaseModel):
    positions: list[PositionIn]
    errors: list[ParseError]


class CatalogOut(BaseModel):
    """Позиция справочника. Поля цены здесь нет и не будет (ADR-017)."""

    found: bool
    name: str = ""
    unit: str = Field(default="", description="Каноническая единица из /units")
    kind: str = Field(default="", description="work или material")
    aliases: list[str] = Field(default_factory=list)


class Health(BaseModel):
    status: str
    core: str

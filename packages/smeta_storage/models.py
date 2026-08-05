"""Таблицы. Деньги — целые минорные единицы, Decimal появляется только в свойствах.

Здесь документ — смета и её строки, то есть ровно то, что видит заказчик.
Всё остальное живёт в records.py и реэкспортируется отсюда: `Base.metadata`
обязана знать про все таблицы, а вызывающие — не обязаны знать про разрез.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from smeta_core import (
    Category,
    EstimateStatus,
    PositionData,
    RateBase,
    from_bp,
    from_kop,
    from_milli,
)

from .base import DEFAULT_MARKUP_BP, Base, utcnow
from .records import PendingPosition, PriceHistory, ShareLink, UserState

__all__ = [
    "DEFAULT_MARKUP_BP",
    "Base",
    "Estimate",
    "PendingPosition",
    "Position",
    "PriceHistory",
    "ShareLink",
    "UserState",
    "utcnow",
]


class Estimate(Base):
    """Смета. С Sprint 7 — версия документа, а не изменяемая запись.

    Номер человекочитаем и переживает правки; версия растёт при каждой правке
    после отправки. Пара (номер, версия) уникальна у владельца — заказчику
    документ подписывается «Смета № 3, ред. 2», и спор «какую вы присылали»
    решается ссылкой на неё (money.md §1.4).
    """

    __tablename__ = "estimates"
    __table_args__ = (
        UniqueConstraint("user_id", "number", "version", name="uq_estimate_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int] = mapped_column(Integer)  # нумерация внутри пользователя
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimates.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default=EstimateStatus.DRAFT)
    markup_work_bp: Mapped[int] = mapped_column(Integer, default=DEFAULT_MARKUP_BP)
    markup_material_bp: Mapped[int] = mapped_column(Integer, default=DEFAULT_MARKUP_BP)
    # От чего берётся процент — условие договора с заказчиком, поэтому свойство
    # сметы целиком, а не строки. Ставок при этом по-прежнему две: договор
    # вполне может удерживать с работ и возмещать материалы по счёту (ADR-024).
    rate_base: Mapped[str] = mapped_column(String(8), default=RateBase.COST)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # Снимок на момент отправки. У черновика пусто: производные значения не
    # хранятся, пока документ можно менять (money.md §1.2).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    frozen_subtotal_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frozen_markup_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frozen_total_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frozen_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Каким форматом посчитан слепок. Проверяется тем же, а не текущим: правка
    # алгоритма не должна обнулять документы, которые уже у людей на руках.
    frozen_format: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Согласована смета, а не ссылка, по которой её открыли: адрес можно
    # отозвать и выдать новый, а согласие заказчика от этого не исчезает
    # (ADR-020). Ссылке остаётся доступ — срок, отзыв, отметки просмотра.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def markup_work_rate(self) -> Decimal:
        return from_bp(self.markup_work_bp)

    @property
    def markup_material_rate(self) -> Decimal:
        return from_bp(self.markup_material_bp)

    @property
    def is_draft(self) -> bool:
        return self.status == EstimateStatus.DRAFT

    @property
    def frozen_total(self) -> Decimal | None:
        return None if self.frozen_total_kop is None else from_kop(self.frozen_total_kop)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    estimate_id: Mapped[int | None] = mapped_column(ForeignKey("estimates.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(16))  # "material" | "work"
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(32), default="")
    # Единица так, как её назвал человек: «мешков», «квадратов». Печатается
    # в документе заказчику; канон выше — для аналитики (ADR-015).
    unit_spoken: Mapped[str] = mapped_column(String(64), default="")
    # Целые минорные единицы: SQLite хранит NUMERIC как REAL, то есть деньги
    # в Numeric(18,2) лежали бы в binary float (ADR-004).
    qty_milli: Mapped[int] = mapped_column(Integer, default=0)
    price_kop: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def qty(self) -> Decimal:
        return from_milli(self.qty_milli)

    @property
    def price(self) -> Decimal:
        return from_kop(self.price_kop)

    def to_domain(self) -> PositionData:
        return PositionData(
            category=Category(self.category),
            name=self.name,
            qty=self.qty,
            price=self.price,
            unit=self.unit or "",
            unit_spoken=self.unit_spoken or "",
        )

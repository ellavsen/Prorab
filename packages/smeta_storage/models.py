"""Таблицы. Деньги — целые минорные единицы, Decimal появляется только в свойствах."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from smeta_core import Category, PositionData, from_bp, from_kop, from_milli

# Наценка по умолчанию для НОВЫХ смет, в базисных пунктах: 600 = 6.00%.
# Копируется в смету при создании и дальше живёт в документе (ADR-003).
DEFAULT_MARKUP_BP = 600


def utcnow() -> datetime:
    """Наивный UTC.

    datetime.utcnow() устарел в 3.12. Значение с таймзоной поменяло бы формат
    хранения в SQLite и сломало бы сортировку по смешанной базе, поэтому
    оставляем наивный UTC, но получаем его не устаревшим способом.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int] = mapped_column(Integer)  # нумерация внутри пользователя
    name: Mapped[str] = mapped_column(String(255))
    markup_work_bp: Mapped[int] = mapped_column(Integer, default=DEFAULT_MARKUP_BP)
    markup_material_bp: Mapped[int] = mapped_column(Integer, default=DEFAULT_MARKUP_BP)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def markup_work_rate(self) -> Decimal:
        return from_bp(self.markup_work_bp)

    @property
    def markup_material_rate(self) -> Decimal:
        return from_bp(self.markup_material_bp)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    estimate_id: Mapped[int | None] = mapped_column(ForeignKey("estimates.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(16))  # "Материал" | "Работа"
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(32), default="")
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
        )


class UserState(Base):
    """Состояние диалога. Раньше жило в dict'ах процесса и умирало с рестартом."""

    __tablename__ = "user_state"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    current_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimates.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

"""Таблицы. Деньги — целые минорные единицы, Decimal появляется только в свойствах."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from smeta_core import (
    Category,
    EstimateStatus,
    PositionData,
    from_bp,
    from_kop,
    from_milli,
)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # Снимок на момент отправки. У черновика пусто: производные значения не
    # хранятся, пока документ можно менять (money.md §1.2).
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    frozen_subtotal_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frozen_markup_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frozen_total_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frozen_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

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


class PendingPosition(Base):
    """Позиция, распознанная моделью, но ещё не подтверждённая человеком.

    Хранится ровно так, как её вернула модель — строками. Деньгами это станет
    только после проверки доменом, и только если человек нажмёт «Добавить»
    (ADR-012). Причина, по которой строка не годится, тоже хранится: пустой
    предпросмотр вместо объяснения — это тихая потеря данных.
    """

    __tablename__ = "pending_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id"))
    ordinal: Mapped[int] = mapped_column(Integer)  # номер в предпросмотре, 1..N
    category: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(32), default="")
    unit_spoken: Mapped[str] = mapped_column(String(64), default="")
    # Как модель поняла цену: per_unit | total | unknown. unknown считается
    # как per_unit, но подсказывает человеку кнопку «÷» (ADR-012).
    price_scope: Mapped[str] = mapped_column(String(16), default="per_unit")
    qty: Mapped[str] = mapped_column(String(32), default="")
    price: Mapped[str] = mapped_column(String(32), default="")
    # Что было сказано до схлопывания «за всё» — по этим полям кнопка
    # «Разбить на позиции» знает, что делить, на сколько и как это назвать.
    total_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_qty: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    problem: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Подсказка цены по своей истории: откуда взялось предложение и что
    # предлагается. Провенанс живёт здесь и умирает вместе с предпросмотром —
    # после подтверждения это просто цена, и доменной модели знать о ней
    # нечего (ADR-017).
    hint_price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hint_median: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hint_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    hint_times: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PriceHistory(Base):
    """Своя цена, пережившая свою смету.

    Ретеншен оставляет пять смет, остальные удаляет вместе с позициями — и
    вместе со знанием о ценах, которое человек ввёл руками. Документ тяжёлый,
    цена — пять полей, поэтому перед удалением она сюда переписывается: это
    меньшее хранение, а не новое (ADR-017).

    Персональное поле здесь ровно одно и то же, что уже есть в positions, —
    user_id. Пересечение историй между пользователями это краудсорсинг, то
    есть Sprint 6b; здесь каждый видит только своё.

    unit_spoken лежит в приведённой форме («мешков» → «мешок»), иначе падежи
    одного слова плодили бы строки и мешали дедупликации.
    """

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "name_norm", "unit", "unit_spoken", "observed_on",
            name="uq_price_history_day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    # Имя, нормализованное на момент сброса: справочник потом меняется,
    # а история от этого ломаться не должна.
    name_norm: Mapped[str] = mapped_column(String(255), index=True)
    unit: Mapped[str] = mapped_column(String(32), default="")
    unit_spoken: Mapped[str] = mapped_column(String(64), default="")
    price_kop: Mapped[int] = mapped_column(Integer)
    observed_on: Mapped[date] = mapped_column(Date)

    @property
    def price(self) -> Decimal:
        return from_kop(self.price_kop)


class ShareLink(Base):
    """Публичная ссылка на смету. Предъявительская: кто знает адрес, тот и смотрит.

    В базе лежит только SHA-256 от токена. Открытым текстом токен существует
    один раз — в сообщении бота в момент выдачи. Ни дамп таблицы, ни бэкап, ни
    отладочный SELECT не содержат работающего адреса (ADR-020).

    Про того, кто открыл, не хранится ничего: ни адрес, ни браузер, ни счётчик
    заходов. Прораб видит два факта — открыли и когда, — потому что без них
    ссылка не даёт доверия, которое обычно даёт регистрация. Больше ему знать
    не нужно, а нам — тем более.

    Владельца здесь нет: он определяется через смету. Токен ничего не выводит
    ни из её id, ни из user_id — урок Sprint 0, где user_id утёк в имя файла.
    """

    __tablename__ = "share_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    estimate_id: Mapped[int] = mapped_column(ForeignKey("estimates.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Согласованная смета живёт, пока владелец не отозвал: approved_at снимает
    # срок (ADR-020). Поэтому здесь NULL — это «бессрочно», а не «просрочено».
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def is_live(self) -> bool:
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > utcnow()
        )


class UserState(Base):
    """Состояние диалога. Раньше жило в dict'ах процесса и умирало с рестартом.

    Здесь же черновик наполовину введённой позиции: рестарт посреди пошагового
    ввода не должен стоить пользователю набранного (ADR-010).
    """

    __tablename__ = "user_state"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    current_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimates.id", ondelete="SET NULL"), nullable=True
    )

    # Шаг пошагового ввода: name | qty | unit | price | confirm | ambiguous.
    draft_step: Mapped[str | None] = mapped_column(String(16), nullable=True)
    draft_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    draft_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    draft_qty_milli: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draft_price_kop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Строка свободного формата, которую не удалось прочитать однозначно.
    pending_line: Mapped[str | None] = mapped_column(String(512), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def draft_qty(self) -> Decimal | None:
        return None if self.draft_qty_milli is None else from_milli(self.draft_qty_milli)

    @property
    def draft_price(self) -> Decimal | None:
        return None if self.draft_price_kop is None else from_kop(self.draft_price_kop)

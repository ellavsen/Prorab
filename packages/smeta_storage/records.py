"""Таблицы, которые не документ: предпросмотр, история цен, ссылка, состояние.

Разрез с models.py проходит по одному признаку — попадает ли строка в смету,
которую видит заказчик. Здесь не попадает ничего: предпросмотр умирает при
подтверждении, история переживает свою смету уже без неё, ссылка хранит
доступ, состояние — незаконченный диалог.

Причина разреза прозаична и названа прямо: один файл на все таблицы упёрся
в лимит длины (конституция, правило 6). Граница выбрана так, чтобы её можно
было объяснить, а не по номеру строки.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from smeta_core import from_kop, from_milli

from .base import Base, utcnow


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
    # Наблюдённый разброс: минимум и максимум того, что человек платил сам.
    # Показываются вместо одного числа, чтобы последняя цена не выдавалась
    # за единственную известную (ADR-026).
    hint_low: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hint_high: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Наименование, под которым цена нашлась, если оно не то, что написано
    # в строке. Подставлять цену от похожей позиции молча нельзя (ADR-027).
    hint_matched_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Кто делает эту строку. Пусто у всех, кто исполнителями не пользуется:
    # поле включается употреблением, а не настройкой (ADR-028).
    performer: Mapped[str] = mapped_column(String(64), default="")
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

    Состав пополнялся один раз, в Sprint 9: исполнитель и категория. Оба поля
    уже есть в positions, оба нужны, чтобы история не отвечала числом, которого
    никто не называл (ADR-017, поправка Sprint 9).
    """

    __tablename__ = "price_history"
    __table_args__ = (
        # Исполнитель и категория входят в ключ дня: Саня за 150 и Паша за 250
        # в один день на одной работе — две цены, а не повтор одной, и «ГКЛ»
        # как материал не то же, что «ГКЛ» как работа. Без них вторая цена
        # исчезала бы молча — ровно в тех случаях, ради которых оба поля и
        # заводились (ADR-028).
        UniqueConstraint(
            "user_id", "name_norm", "unit", "unit_spoken", "category", "performer",
            "observed_on", name="uq_price_history_day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    # Имя, нормализованное на момент сброса: справочник потом меняется,
    # а история от этого ломаться не должна.
    name_norm: Mapped[str] = mapped_column(String(255), index=True)
    unit: Mapped[str] = mapped_column(String(32), default="")
    unit_spoken: Mapped[str] = mapped_column(String(64), default="")
    # Работа это была или материал. Без категории «ГКЛ» и «ГКЛ монтаж»
    # неотличимы, а цена у них разная в разы (ADR-027).
    category: Mapped[str] = mapped_column(String(16), default="")
    # Чья это цена. Ставка Сани и ставка Паши — не разброс одной цены,
    # а две разные (ADR-028).
    performer: Mapped[str] = mapped_column(String(64), default="")
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

    Здесь только доступ: срок, отзыв, отметки просмотра. Факт согласования
    живёт на смете — согласовывают документ, а не адрес, по которому его
    открыли, и переезд на новую ссылку не должен его терять.

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

    # Липкий исполнитель: кого проставлять следующим пачкам. Видим в каждом
    # предпросмотре и потому не бывает забытым (ADR-028). Отметка времени
    # скользящая — обновляется при каждом употреблении, а не при установке:
    # отвалившийся посреди рабочего дня хуже прилипшего.
    current_performer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    performer_touched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def draft_qty(self) -> Decimal | None:
        return None if self.draft_qty_milli is None else from_milli(self.draft_qty_milli)

    @property
    def draft_price(self) -> Decimal | None:
        return None if self.draft_price_kop is None else from_kop(self.draft_price_kop)

"""Группа F: неизменяемость и версии (money.md §1.3–1.4, тесты F1–F10, C7, C10).

Смета после отправки — документ, а не запись в базе. «Отправлено заказчику»
значит «по этому выставлен счёт», поэтому правка создаёт новую версию, а
старая остаётся ровно такой, какой её увидел заказчик.
"""

from decimal import Decimal as D

import pytest
from sqlalchemy import text

from conftest import open_storage
from smeta_core import (
    Category,
    EstimateStatus,
    IntegrityError,
    PositionData,
    RateBase,
    calculate_estimate,
    canonical_form,
    diff_positions,
    from_kop,
    frozen_hash,
)
from smeta_storage import (
    RETENTION_LIMIT,
    FrozenEstimateError,
    StateError,
    create_estimate,
    enforce_retention,
    history_of,
    list_estimates,
    positions,
    revise,
    send,
    set_rates,
    verified_totals,
)

UID = 42
RATE = D("6.00")


def position(name="Побелка", qty="150", price="3000", category=Category.WORK):
    return PositionData(category=category, name=name, qty=D(qty), price=D(price), unit="м²")


@pytest.fixture
def db(tmp_path):
    _engine, Session = open_storage(tmp_path / "versions.db")
    with Session() as session:
        yield session


def drafted(db, *items) -> object:
    estimate = create_estimate(db, UID, name="Смета")
    for item in items or (position(),):
        positions.add(db, UID, estimate.id, item)
    db.commit()
    return estimate


# --- F3, C7: заморозка ---


def test_f3_sending_freezes_the_totals_and_the_snapshot(db):
    estimate = send(db, drafted(db))

    assert estimate.status == EstimateStatus.SENT
    assert estimate.sent_at is not None
    assert estimate.frozen_hash and len(estimate.frozen_hash) == 64
    expected = calculate_estimate([position()], RATE, RATE)
    assert from_kop(estimate.frozen_total_kop) == expected.total
    assert from_kop(estimate.frozen_subtotal_kop) == expected.subtotal
    assert from_kop(estimate.frozen_markup_kop) == expected.markup


def test_c7_recomputing_a_frozen_estimate_gives_the_frozen_numbers(db):
    estimate = send(db, drafted(db))
    assert verified_totals(db, estimate).total == estimate.frozen_total


def test_f10_sending_twice_is_refused_not_ignored(db):
    """«Отправить ещё раз» и «отправить изменённое» человек различает плохо."""
    estimate = send(db, drafted(db))
    with pytest.raises(StateError, match="уже не черновик"):
        send(db, estimate)


def test_an_empty_estimate_is_not_a_document(db):
    with pytest.raises(StateError, match="нет позиций"):
        send(db, create_estimate(db, UID, name="Пустая"))


# --- F1, F2, F8: неизменяемость ---


def test_f1_a_position_cannot_be_added_to_a_sent_estimate(db):
    estimate = send(db, drafted(db))
    with pytest.raises(FrozenEstimateError, match="отправлена заказчику"):
        positions.add(db, UID, estimate.id, position(name="Стяжка"))


def test_f1_positions_of_a_sent_estimate_cannot_be_cleared(db):
    estimate = send(db, drafted(db))
    with pytest.raises(FrozenEstimateError):
        positions.clear(db, UID, estimate.id)


def test_f8_rates_of_a_sent_estimate_do_not_change(db):
    """Ставка — часть документа: она напечатана и у заказчика на руках."""
    estimate = send(db, drafted(db))
    with pytest.raises(FrozenEstimateError):
        set_rates(db, estimate, 1000, 1000)


def test_the_refusal_tells_the_human_what_to_do(db):
    estimate = send(db, drafted(db))
    with pytest.raises(FrozenEstimateError, match="/revise"):
        positions.add(db, UID, estimate.id, position(name="Стяжка"))


def test_f4_tampering_behind_the_domain_is_caught_before_the_document(db):
    """Проверка в хранилище — не единственный рубеж: слепок ловит и обход.

    money.md И4 допускает триггер ИЛИ проверку в репозитории; проверка стоит.
    Но если данные подменили мимо неё, документ всё равно не выдаётся: перед
    выдачей пересчёт сверяется со слепком (И3).
    """
    estimate = send(db, drafted(db))
    db.execute(text("UPDATE positions SET price_kop = 999900 WHERE estimate_id = :i"),
               {"i": estimate.id})
    db.commit()
    db.expire_all()

    with pytest.raises(IntegrityError, match="слепок не совпадает"):
        verified_totals(db, estimate)


# --- F5, F6, F7, F9: версии ---


def test_f5_revising_copies_everything_into_a_new_draft(db):
    estimate = send(db, drafted(db, position(), position(name="Стяжка", price="700")))
    revision = revise(db, estimate)

    assert (revision.number, revision.version) == (estimate.number, estimate.version + 1)
    assert revision.status == EstimateStatus.DRAFT
    assert revision.supersedes_id == estimate.id
    assert revision.markup_work_bp == estimate.markup_work_bp

    before = [row.to_domain() for row in positions.load(db, UID, estimate.id)]
    after = [row.to_domain() for row in positions.load(db, UID, revision.id)]
    assert after == before


def test_f5_revising_carries_the_contract_over_field_by_field(db):
    """Ревизия — тот же договор, следующая редакция.

    Поимённо, а не «поля скопированы»: сравнение объектов целиком пришлось бы
    ослаблять при каждом новом столбце, и однажды оно перестало бы ловить то,
    ради чего написано. Проверено впрыском — без строки `rate_base=` в revise()
    все 1561 теста проекта оставались зелёными, а редакция сметы с процентом от
    суммы заказчику молча превращалась в смету с обычной наценкой.
    """
    estimate = drafted(db)
    estimate.rate_base = RateBase.PRICE
    set_rates(db, estimate, work_bp=600, material_bp=0)
    revision = revise(db, send(db, estimate))

    for field in ("rate_base", "markup_work_bp", "markup_material_bp", "name"):
        assert getattr(revision, field) == getattr(estimate, field), field
    assert verified_totals(db, revision).total == estimate.frozen_total


def test_f6_the_old_version_stays_current_until_the_new_one_is_sent(db):
    """Правка «на пробу» не обесценивает документ, который уже у заказчика."""
    first = send(db, drafted(db))
    revision = revise(db, first)
    assert first.status == EstimateStatus.SENT

    positions.add(db, UID, revision.id, position(name="Стяжка", price="700"))
    send(db, revision)
    db.refresh(first)
    assert first.status == EstimateStatus.SUPERSEDED


def test_f7_a_draft_is_edited_directly_not_revised(db):
    with pytest.raises(StateError, match="только с отправленной"):
        revise(db, drafted(db))


def test_f9_one_number_and_version_belong_to_one_document(db):
    estimate = send(db, drafted(db))
    revise(db, estimate)
    versions = history_of(db, UID, estimate.number)
    assert [e.version for e in versions] == [1, 2]
    assert len({(e.number, e.version) for e in versions}) == 2


def test_editing_a_revision_does_not_touch_what_the_customer_has(db):
    """Главное свойство спринта, выраженное числами."""
    first = send(db, drafted(db))
    frozen = first.frozen_total

    revision = revise(db, first)
    positions.add(db, UID, revision.id, position(name="Грунтовка", price="500"))
    db.commit()

    db.refresh(first)
    assert first.frozen_total == frozen
    assert verified_totals(db, first).total == frozen
    assert verified_totals(db, revision).total > frozen


# --- Ретеншен: пятёрка была про черновики (ADR-019) ---


def test_a_sent_estimate_survives_the_sixth_draft(db):
    """Документ не может исчезнуть потому, что автор начал новую смету."""
    sent = send(db, drafted(db))
    for _ in range(RETENTION_LIMIT + 1):
        create_estimate(db, UID, name="Черновик")
    enforce_retention(db, UID)

    db.refresh(sent)
    assert sent.status == EstimateStatus.SENT
    assert positions.load(db, UID, sent.id), "позиции отправленной сметы на месте"


def test_drafts_are_still_capped(db):
    for _ in range(RETENTION_LIMIT + 3):
        create_estimate(db, UID, name="Черновик")
    enforce_retention(db, UID)

    alive = [e for e in list_estimates(db, UID, limit=99)]
    assert len(alive) == RETENTION_LIMIT


def test_sent_estimates_do_not_use_up_the_draft_quota(db):
    """Иначе пять отправленных документов лишили бы человека черновиков."""
    for _ in range(3):
        send(db, drafted(db))
    for _ in range(RETENTION_LIMIT):
        create_estimate(db, UID, name="Черновик")
    enforce_retention(db, UID)

    alive = list_estimates(db, UID, limit=99)
    assert len([e for e in alive if e.status == EstimateStatus.DRAFT]) == RETENTION_LIMIT
    assert len([e for e in alive if e.status == EstimateStatus.SENT]) == 3


def test_a_superseded_version_is_kept_too(db):
    """У заказчика на руках может быть именно она."""
    first = send(db, drafted(db))
    revision = revise(db, first)
    positions.add(db, UID, revision.id, position(name="Стяжка", price="700"))
    send(db, revision)

    for _ in range(RETENTION_LIMIT + 1):
        create_estimate(db, UID, name="Черновик")
    enforce_retention(db, UID)

    db.refresh(first)
    assert first.status == EstimateStatus.SUPERSEDED
    assert verified_totals(db, first).total == first.frozen_total


# --- C10: канонический слепок ---


def test_c10_the_snapshot_ignores_how_the_data_was_written():
    """Порядок полей и незначащие нули — не изменение документа."""
    plain = PositionData(Category.WORK, "Побелка", D("150"), D("3000"), unit="м²")
    verbose = PositionData(
        price=D("3000.00"), qty=D("150.000"), name="Побелка",
        category=Category.WORK, unit="м²",
    )
    assert frozen_hash([plain], RATE, RATE) == frozen_hash([verbose], RATE, RATE)
    assert canonical_form([plain], RATE, RATE) == canonical_form([verbose], RATE, RATE)


def test_c10_one_kopeck_changes_the_snapshot():
    before = [PositionData(Category.WORK, "Побелка", D("150"), D("3000.00"))]
    after = [PositionData(Category.WORK, "Побелка", D("150"), D("3000.01"))]
    assert frozen_hash(before, RATE, RATE) != frozen_hash(after, RATE, RATE)


def test_c10_the_rate_is_part_of_the_snapshot():
    rows = [PositionData(Category.WORK, "Побелка", D("150"), D("3000"))]
    assert frozen_hash(rows, RATE, RATE) != frozen_hash(rows, D("7.00"), RATE)


def test_c10_reordering_positions_is_a_change_of_the_document():
    """Документ упорядочен: заказчик читает строки сверху вниз."""
    first = PositionData(Category.WORK, "Побелка", D("1"), D("100"))
    second = PositionData(Category.WORK, "Стяжка", D("1"), D("100"))
    assert frozen_hash([first, second], RATE, RATE) != frozen_hash([second, first], RATE, RATE)


def test_the_spoken_unit_is_part_of_the_snapshot():
    """Оно печатается заказчику, значит его подмена — изменение документа."""
    bags = [PositionData(Category.MATERIAL, "Цемент", D("20"), D("350"), unit_spoken="мешок")]
    pieces = [PositionData(Category.MATERIAL, "Цемент", D("20"), D("350"), unit_spoken="шт")]
    assert frozen_hash(bags, RATE, RATE) != frozen_hash(pieces, RATE, RATE)


# --- Дифф версий ---


def test_the_diff_tells_added_removed_and_repriced_apart():
    before = [position(), position(name="Стяжка", price="700")]
    after = [position(price="3100"), position(name="Грунтовка", price="500")]
    changes = diff_positions(before, after)

    assert [p.name for p in changes.added] == ["Грунтовка"]
    assert [p.name for p in changes.removed] == ["Стяжка"]
    assert [c.after.name for c in changes.changed] == ["Побелка"]
    assert changes.changed[0].price_delta == D("100")
    assert not changes.empty


def test_an_unchanged_estimate_has_an_empty_diff():
    rows = [position(), position(name="Стяжка", price="700")]
    assert diff_positions(rows, list(rows)).empty


def test_the_same_name_in_another_category_is_another_position():
    """«Гидроизоляция» как работа и как материал — разные строки сметы."""
    work = position(name="Гидроизоляция", category=Category.WORK)
    material = position(name="Гидроизоляция", category=Category.MATERIAL)
    changes = diff_positions([work], [material])
    assert len(changes.added) == len(changes.removed) == 1
    assert not changes.changed

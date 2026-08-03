"""Публичная ссылка: что видит человек с ней и чего не видит без неё.

Первый раз проект отдаёт данные наружу без аутентификации, поэтому проверяется
не «страница открылась», а три отдельных свойства (ADR-020):

  — со ссылкой видно ровно смету и ничего о владельце;
  — при переборе токенов не видно ничего, включая ответ «такой токен был»;
  — токен не попадает ни в журнал, ни в базу открытым текстом.
"""

import logging
import os
from datetime import timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_document_naming import UID, FakeDocumentMessage, FakeUpdate

from conftest import async_test, open_storage
from smeta_core import Category, EstimateStatus, PositionData, format_money
from smeta_storage import (
    Estimate,
    FrozenEstimateError,
    ShareLink,
    StateError,
    create_estimate,
    positions,
    revise,
    send,
    set_current_estimate,
    share,
    utcnow,
    verified_totals,
)

RATE = D("6.00")


def rows():
    return [
        PositionData(Category.WORK, "Побелка потолка", D("150"), D("3000"), unit="м²"),
        PositionData(Category.MATERIAL, "Цемент М500", D("20"), D("380"),
                     unit="", unit_spoken="мешков"),
    ]


@pytest.fixture
def storage(tmp_path):
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'share.db'}"
    _engine, Session = open_storage(tmp_path / "share.db")
    return Session


def sent_estimate(Session, name="Ремонт у Ивановых"):
    """Отправленная смета с позициями и живой ссылкой на неё."""
    with Session() as db:
        estimate = create_estimate(db, UID, name=name)
        set_current_estimate(db, UID, estimate.id)
        for item in rows():
            positions.add(db, UID, estimate.id, item)
        db.commit()
        send(db, estimate)
        token = share.issue(db, estimate)
        return estimate.id, token


@pytest.fixture
def client(storage, monkeypatch):
    from share import routes

    monkeypatch.setattr(routes, "SessionLocal", storage)
    from share.main import app

    return TestClient(app)


# --- Токен ---


def test_the_token_is_derived_from_nothing(storage):
    """Урок Sprint 0: id владельца утёк в имя файла. Здесь выводить нечего.

    Про id сметы подстрокой не проверить — он однозначный, и «1» найдётся в
    любой случайной строке. Что токен не функция от сметы, показывает
    следующий тест: две выдачи на одну и ту же смету не совпадают.
    """
    _estimate_id, token = sent_estimate(storage)
    assert str(UID) not in token
    assert len(token) >= 40
    assert set(token) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


def test_two_links_on_one_estimate_are_unrelated(storage):
    estimate_id, first = sent_estimate(storage)
    with storage() as db:
        second = share.issue(db, db.get(Estimate, estimate_id))
    assert first != second
    assert share.digest(first) != share.digest(second)


def test_the_database_holds_the_fingerprint_and_not_the_link(storage):
    """Дамп таблицы, бэкап и отладочный SELECT не содержат рабочего адреса."""
    _estimate_id, token = sent_estimate(storage)
    with storage() as db:
        dump = db.execute(text("SELECT * FROM share_links")).fetchall()
    flat = " ".join(str(value) for row in dump for value in row)
    assert token not in flat
    assert share.digest(token) in flat


def test_a_draft_gets_no_link(storage):
    with storage() as db:
        estimate = create_estimate(db, UID, name="Черновик")
        db.commit()
        with pytest.raises(StateError):
            share.issue(db, db.get(Estimate, estimate.id))


# --- Что открывается, а что нет ---


def test_a_wrong_token_resolves_to_nothing(storage):
    sent_estimate(storage)
    with storage() as db:
        assert share.resolve(db, "не-тот-токен") is None


def test_a_revoked_link_resolves_to_nothing(storage):
    _estimate_id, token = sent_estimate(storage)
    with storage() as db:
        share.revoke(db, share.resolve(db, token))
        assert share.resolve(db, token) is None


def test_an_expired_link_resolves_to_nothing(storage):
    _estimate_id, token = sent_estimate(storage)
    with storage() as db:
        link = share.resolve(db, token)
        link.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        assert share.resolve(db, token) is None


def test_approval_takes_the_expiry_off(storage):
    """Согласованный документ живёт, пока владелец не отозвал (ADR-020)."""
    _estimate_id, token = sent_estimate(storage)
    with storage() as db:
        link = share.approve(db, share.resolve(db, token))
        assert link.approved_at is not None
        assert link.expires_at is None
        link.created_at = utcnow() - timedelta(days=400)
        db.commit()
        assert share.resolve(db, token) is not None


def test_yesterdays_link_keeps_showing_yesterdays_document(storage):
    """Ревизия не подменяет документ, который заказчик уже держит (money.md §1.4)."""
    estimate_id, token = sent_estimate(storage)
    with storage() as db:
        revision = revise(db, db.get(Estimate, estimate_id))
        positions.add(db, UID, revision.id, PositionData(
            Category.WORK, "Ещё работа", D("1"), D("999999"), unit="шт"))
        db.commit()
        send(db, revision)

        shown = share.document(db, share.resolve(db, token))
        assert shown.version == 1
        assert shown.status == "Заменена новой редакцией"
        assert format_money(shown.totals.total) == format_money(
            db.get(Estimate, estimate_id).frozen_total
        )


# --- Отметка просмотра ---


def test_the_first_view_is_remembered_once_and_the_last_every_time(storage):
    _estimate_id, token = sent_estimate(storage)
    with storage() as db:
        link = share.resolve(db, token)
        share.mark_viewed(db, link)
        first, last = link.first_viewed_at, link.last_viewed_at
        assert first is not None and first == last

        link.last_viewed_at = last - timedelta(hours=2)
        db.commit()
        share.mark_viewed(db, link)
        assert link.first_viewed_at == first, "первый просмотр не переписывается"
        assert link.last_viewed_at > link.first_viewed_at - timedelta(seconds=1)


def test_nothing_about_the_viewer_is_stored():
    """Ни адреса, ни браузера, ни счётчика по адресам — это в схеме, не в коде."""
    assert set(ShareLink.__table__.columns.keys()) == {
        "id", "token_sha256", "estimate_id", "created_at", "expires_at",
        "revoked_at", "first_viewed_at", "last_viewed_at", "approved_at",
    }


def test_the_shared_view_names_everything_a_stranger_can_see():
    """Список закрыт: новое поле здесь — решение показать его постороннему."""
    from dataclasses import fields

    assert {field.name for field in fields(share.SharedEstimate)} == {
        "number", "version", "title", "on", "status",
        "work_rate", "material_rate", "totals", "approved_on",
    }


# --- HTTP ---


def test_a_stranger_with_the_link_sees_the_estimate(storage, client):
    estimate_id, token = sent_estimate(storage)
    with storage() as db:
        totals = verified_totals(db, db.get(Estimate, estimate_id))

    response = client.get(f"/e/{token}")
    assert response.status_code == 200
    assert format_money(totals.total) in response.text
    assert "Побелка потолка" in response.text


def test_a_stranger_without_the_link_sees_the_same_page_whatever_he_tries(
    storage, client
):
    """Оракула для перебора нет: «не было», «отозвано» и «истекло» неразличимы."""
    _estimate_id, token = sent_estimate(storage)
    _other, revoked = sent_estimate(storage, name="Вторая")
    with storage() as db:
        share.revoke(db, share.resolve(db, revoked))
        link = share.resolve(db, token)
        link.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    answers = [client.get(f"/e/{value}") for value in ("нет-такого", revoked, token)]
    assert {answer.status_code for answer in answers} == {404}
    assert len({answer.text for answer in answers}) == 1


def test_the_response_carries_the_headers_that_keep_the_page_private(storage, client):
    _estimate_id, token = sent_estimate(storage)
    headers = client.get(f"/e/{token}").headers
    assert headers["referrer-policy"] == "no-referrer"
    assert "noindex" in headers["x-robots-tag"]
    assert headers["cache-control"] == "no-store"
    assert "default-src 'none'" in headers["content-security-policy"]


def test_there_is_no_cors_on_the_public_app(storage, client):
    """У apps/api он открыт всем, потому что там нечего красть. Здесь есть."""
    _estimate_id, token = sent_estimate(storage)
    response = client.get(f"/e/{token}", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_the_public_app_publishes_no_api_surface(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_approving_from_the_page_records_it_and_redirects(storage, client):
    _estimate_id, token = sent_estimate(storage)
    response = client.post(f"/e/{token}/approve", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/e/{token}"

    with storage() as db:
        assert share.resolve(db, token).approved_at is not None
    assert "Согласовано" in client.get(f"/e/{token}").text


def test_opening_the_page_changes_the_estimate_in_no_way(storage, client):
    """Поведенческая пара к запрету записи в тесте архитектуры."""
    _estimate_id, token = sent_estimate(storage)

    def snapshot():
        with storage() as db:
            return (
                db.execute(text("SELECT * FROM estimates ORDER BY id")).fetchall(),
                db.execute(text("SELECT * FROM positions ORDER BY id")).fetchall(),
            )

    before = snapshot()
    client.get(f"/e/{token}")
    client.post(f"/e/{token}/approve", follow_redirects=False)
    assert snapshot() == before


def test_a_document_that_disagrees_with_its_snapshot_is_not_shown(storage, client, caplog):
    """money.md И3: разошлось — не выдаём. Заказчику та же нейтральная страница."""
    estimate_id, token = sent_estimate(storage)
    with storage() as db:
        db.execute(text("UPDATE positions SET price_kop = 1 WHERE estimate_id = :i"),
                   {"i": estimate_id})
        db.commit()

    with caplog.at_level(logging.WARNING, logger="prorab.share"):
        response = client.get(f"/e/{token}")
    assert response.status_code == 404
    assert "Ссылка недоступна" in response.text
    assert any("не отдана" in record.message for record in caplog.records)


# --- Журнал ---


def test_the_token_never_reaches_the_log(storage, client, caplog):
    _estimate_id, token = sent_estimate(storage)
    with caplog.at_level(logging.INFO, logger="prorab.share"):
        client.get(f"/e/{token}")
        client.post(f"/e/{token}/approve", follow_redirects=False)

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert token not in logged
    assert "/e/***" in logged
    assert "/e/***/approve" in logged, "что сделали — остаётся, с чем — уходит"


def test_the_access_log_of_the_server_is_redacted_too():
    """uvicorn пишет мимо приложения, поэтому фильтр ставится и на его журнал."""
    from share import logs

    logs.install("uvicorn.access")
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:52000", "GET", "/e/SECRET-TOKEN-VALUE", "1.1", 200),
        None,
    )
    assert all(item.filter(record) for item in logging.getLogger("uvicorn.access").filters)
    assert "SECRET-TOKEN-VALUE" not in record.getMessage()
    assert "/e/***" in record.getMessage()


def test_installing_the_filter_twice_does_not_double_it():
    from share import logs

    logs.install("uvicorn.access")
    logs.install("uvicorn.access")
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(item, logs.RedactToken) for item in filters) == 1


# --- Бот ---


@async_test
async def test_send_freezes_the_estimate_and_warns_about_the_title(storage, monkeypatch):
    from bot.handlers import share as handler

    monkeypatch.setattr(handler, "SessionLocal", storage)
    with storage() as db:
        estimate = create_estimate(db, UID, name="Ремонт у Ивановых")
        set_current_estimate(db, UID, estimate.id)
        for item in rows():
            positions.add(db, UID, estimate.id, item)
        db.commit()

    message = FakeDocumentMessage()
    await handler.cmd_send(FakeUpdate(message), None)

    [text_out] = message.sent
    assert "Страница увидит название сметы" in text_out
    assert "/e/" in text_out
    assert str(UID) not in text_out

    with storage() as db:
        assert db.get(Estimate, estimate.id).status == EstimateStatus.SENT


@async_test
async def test_revise_opens_a_new_draft_and_leaves_the_old_one_working(
    storage, monkeypatch
):
    from bot.handlers import share as handler

    monkeypatch.setattr(handler, "SessionLocal", storage)
    estimate_id, token = sent_estimate(storage)

    message = FakeDocumentMessage()
    await handler.cmd_revise(FakeUpdate(message), None)
    assert "ред. 2" in message.sent[0]

    with storage() as db:
        assert db.get(Estimate, estimate_id).status == EstimateStatus.SENT
        assert share.resolve(db, token) is not None


@async_test
async def test_a_sent_estimate_answers_instead_of_crashing(storage):
    """Охрана из guards.py впервые достижима из бота — значит, её отказ виден."""
    from bot.handlers import errors

    estimate_id, _token = sent_estimate(storage)
    with storage() as db, pytest.raises(FrozenEstimateError) as caught:
        positions.add(db, UID, estimate_id, PositionData(
            Category.WORK, "Поздняя правка", D("1"), D("100")))

    message = FakeDocumentMessage()

    class FakeContext:
        error = caught.value

    class FakeUpdateWithMessage:
        effective_message = message

    await errors.on_error(FakeUpdateWithMessage(), FakeContext())
    assert "Сделай ревизию: /revise" in message.sent[0]


@async_test
async def test_revoking_an_approved_link_asks_first(storage, monkeypatch):
    from bot.handlers import share as handler

    monkeypatch.setattr(handler, "SessionLocal", storage)
    _estimate_id, token = sent_estimate(storage)
    with storage() as db:
        share.approve(db, share.resolve(db, token))

    message = FakeDocumentMessage()
    await handler.cmd_revoke(FakeUpdate(message), None)
    assert "уже согласовал" in message.sent[0]

    with storage() as db:
        assert share.resolve(db, token) is not None, "без подтверждения не отзываем"


@async_test
async def test_revoking_an_unapproved_link_happens_at_once(storage, monkeypatch):
    from bot.handlers import share as handler

    monkeypatch.setattr(handler, "SessionLocal", storage)
    _estimate_id, token = sent_estimate(storage)

    message = FakeDocumentMessage()
    await handler.cmd_revoke(FakeUpdate(message), None)
    assert "отозвана" in message.sent[0].lower()

    with storage() as db:
        assert share.resolve(db, token) is None

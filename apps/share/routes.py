"""Два маршрута: посмотреть смету и согласовать её.

Приложение ничего не считает и ничего не пишет само: суммы приходят из домена
после сверки со слепком, а обе записи — отметка просмотра и согласование —
живут в smeta_storage.share. Что это действительно так, проверяет тест
архитектуры, а не дисциплина.
"""

import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from smeta_export import DocumentMeta, build_page, unavailable_page
from smeta_storage import share

from .database import SessionLocal

router = APIRouter()
logger = logging.getLogger("prorab.share")

# Один код на все отказы. Другой код — это оракул: он отвечает на вопрос
# «а такой токен вообще существовал?», а отвечать на него незачем.
GONE = 404


def _gone() -> HTMLResponse:
    return HTMLResponse(unavailable_page(), status_code=GONE)


def _meta(shared: share.SharedEstimate) -> DocumentMeta:
    return DocumentMeta(
        number=shared.number,
        version=shared.version,
        title=shared.title,
        on=shared.on,
        work_rate=shared.work_rate,
        material_rate=shared.material_rate,
        status=shared.status,
        rate_base=shared.rate_base,
    )


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/e/{token}", response_class=HTMLResponse)
def open_estimate(token: str) -> Response:
    with SessionLocal() as db:
        link = share.resolve(db, token)
        if link is None:
            return _gone()
        try:
            shared = share.document(db, link)
        except ValueError as error:
            # Расхождение со слепком или пропавшая смета. Заказчику — та же
            # нейтральная страница, владельцу — запись в журнале: показывать
            # документ, разошедшийся с отправленным, нельзя (money.md И3).
            logger.warning("Смета %s не отдана: %s", link.estimate_id, error)
            return _gone()
        share.mark_viewed(db, link)

    return HTMLResponse(build_page(
        shared.totals,
        _meta(shared),
        approve_url=None if shared.approved_on else f"/e/{token}/approve",
        approved_on=shared.approved_on,
    ))


@router.post("/e/{token}/approve")
def approve_estimate(token: str) -> Response:
    """Согласование. Единственное, что заказчик может изменить, — этот факт."""
    with SessionLocal() as db:
        link = share.resolve(db, token)
        if link is None:
            return _gone()
        share.approve(db, link)
    # 303 после POST: обновление страницы не должно согласовывать повторно.
    return RedirectResponse(f"/e/{token}", status_code=303)

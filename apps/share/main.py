"""Публичное приложение. Одна страница по ссылке — ни входа, ни API, ни витрины.

Что видит человек со ссылкой: смету целиком — позиции, количества, цены, итог,
наценку и название документа. Что он видит при переборе токенов: одну и ту же
страницу «ссылка недоступна», одинаковую для «не было», «отозвано», «истекло»
и «данные разошлись со слепком»; никакого способа отличить эти случаи снаружи
нет. Что попадает в журнал: метод, путь без токена и код ответа — ни адреса,
ни браузера (ADR-020).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import Response

from . import logs
from .routes import router

logs.install()
logger = logging.getLogger("prorab.share")

# Страница ничего не грузит извне и никуда не ходит. Заголовки это не защита
# сами по себе — они делают свойство проверяемым и не дают ему тихо исчезнуть
# при следующей правке вёрстки.
SECURITY_HEADERS = {
    # Ни скриптов, ни картинок, ни шрифтов: разрешены только встроенные стили
    # и отправка формы согласования к себе же.
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                               "form-action 'self'; base-uri 'none'",
    # Ссылка не должна уехать в чужой Referer ни при каком переходе.
    "Referrer-Policy": "no-referrer",
    # Смета в поисковой выдаче — это утечка, даже если ссылку никто не отзывал.
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    # Ни прокси, ни браузер не хранят документ после отзыва ссылки.
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

# CORS здесь нет и не будет. У apps/api он открыт всем, потому что там нечего
# красть: ни базы, ни сессий. Здесь есть чужие сметы, и разрешать читать их
# скриптом с любого сайта нельзя (ADR-008, ADR-020).
app = FastAPI(
    title="Прораб — смета по ссылке",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def publish_safely(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    logger.info(
        "%s %s %s", request.method, logs.redact(request.url.path), response.status_code
    )
    return response


app.include_router(router)

"""FastAPI поверх smeta_core. Без состояния: ни базы, ни сессий, ни персональных данных."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import router

DESCRIPTION = """
HTTP-обёртка над детерминированным ядром расчёта смет.

**LLM превращает речь, фото и текст в структуру. Деньги считает код.**

Считает ровно одна функция — `calculate_estimate` в `smeta_core`. Этот API её
не дублирует, а вызывает; XLSX содержит те же значения и живые формулы.

Деньги передаются **строками** (`"159.16"`), а не числами: JSON-число это
double, и копейки на границе терялись бы.
"""

app = FastAPI(
    title="Прораб API",
    version="0.1.0",
    description=DESCRIPTION,
    openapi_tags=[
        {"name": "расчёт", "description": "Суммы и документы по смете"},
        {"name": "ввод", "description": "Разбор пользовательских строк"},
        {"name": "справочники", "description": "Единицы измерения"},
        {"name": "служебное", "description": "Проверка живости"},
    ],
)

# API не хранит состояния и не принимает секретов, поэтому открыт всем источникам.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def domain_error(request: Request, error: ValueError) -> JSONResponse:
    """Отказ домена — это 422 с человеческим текстом, а не 500.

    Границы значений проверяет домен, поэтому его сообщение и есть ответ
    пользователю: «Количество: должно быть больше нуля».
    """
    return JSONResponse(status_code=422, content={"detail": str(error)})


app.include_router(router)

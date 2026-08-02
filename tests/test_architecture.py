"""Правила слоёв, проверяемые машиной, а не ревью (ADR-002, ADR-007)."""

from __future__ import annotations

import ast
import pathlib

import pytest

from smeta_storage import Base, PriceHistory

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "packages" / "smeta_core"
PRICES = ROOT / "packages" / "smeta_prices"
STORAGE = ROOT / "packages" / "smeta_storage"
EXPORT = ROOT / "packages" / "smeta_export"
AI = ROOT / "packages" / "smeta_ai"
BOT = ROOT / "apps" / "bot"
API = ROOT / "apps" / "api"

MAX_FILE_LINES = 300

# Что каждому слою запрещено импортировать (конституция, правило 1).
# openai разрешён ровно в одном месте — в smeta_ai, и только лениво:
# см. test_openai_is_imported_lazily.
FORBIDDEN = {
    CORE: {"telegram", "sqlalchemy", "openpyxl", "requests", "httpx",
           "aiohttp", "fastapi", "pydantic", "dotenv", "openai", "smeta_prices"},
    # Справочник и подсказка — такой же чистый пакет, как ядро: ни базы, ни
    # сети. Историю цен ему передают уже прочитанной (ADR-017).
    PRICES: {"telegram", "sqlalchemy", "openpyxl", "requests", "httpx", "aiohttp",
             "fastapi", "pydantic", "dotenv", "openai", "smeta_storage", "smeta_ai"},
    STORAGE: {"telegram", "openpyxl", "requests", "httpx", "aiohttp", "fastapi",
              "dotenv", "openai", "smeta_ai"},
    EXPORT: {"telegram", "sqlalchemy", "requests", "httpx", "aiohttp", "fastapi",
             "dotenv", "openai"},
    # AI-слой — граница ввода. Ни базы, ни телеграма, ни Excel он не знает.
    AI: {"telegram", "sqlalchemy", "openpyxl", "fastapi", "dotenv",
         "smeta_storage", "smeta_export"},
    BOT: {"sqlalchemy", "openpyxl", "openai"},
    # API без состояния: базы он не касается вовсе (ADR-008).
    API: {"telegram", "sqlalchemy", "openpyxl", "smeta_storage", "openai"},
}


def python_files(*roots: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for root in roots for path in root.rglob("*.py"))


ALL_FILES = python_files(CORE, PRICES, STORAGE, EXPORT, AI, BOT, API)


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _multiplication_lines(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
    ]


def _module_level_imports(tree: ast.AST) -> set[str]:
    """Только импорты на уровне модуля — вложенные в функции сюда не попадают."""
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_every_layer_is_present():
    for layer in (CORE, PRICES, STORAGE, EXPORT, AI, BOT, API):
        assert layer.is_dir(), f"нет слоя {layer}"
    assert len(ALL_FILES) > 15


@pytest.mark.parametrize("path", python_files(AI), ids=lambda p: p.name)
def test_openai_is_imported_lazily(path):
    """Без ключа AI-слой обязан подниматься на стандартной библиотеке.

    Импорт openai на уровне модуля сделал бы пакет обязательной зависимостью
    DEMO-режима, а конституция требует старта с нулём ключей (правило 7).
    """
    top = _module_level_imports(ast.parse(path.read_text(encoding="utf-8")))
    assert "openai" not in top, f"{path.name}: openai импортируется на уровне модуля"


@pytest.mark.parametrize("path", python_files(AI), ids=lambda p: p.name)
def test_the_ai_layer_never_writes_to_the_estimate(path):
    """Тезис проекта, проверяемый машиной: деньги пишет не модель.

    Запись в смету идёт через positions.add, а его в AI-слое нет вовсе. Денег
    здесь тоже нет: слой оперирует строками, Decimal появляется только после
    проверки доменом.
    """
    source = path.read_text(encoding="utf-8")
    assert "positions.add" not in source, f"{path.name}: AI-слой пишет в смету"
    offenders = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name) and node.id == "Decimal"
    ]
    assert not offenders, f"{path.name}: Decimal в строках {offenders}"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_layer_does_not_import_what_it_must_not(path):
    layer = next(root for root in FORBIDDEN if root in path.parents or root == path.parent)
    leaked = _imported_roots(ast.parse(path.read_text(encoding="utf-8"))) & FORBIDDEN[layer]
    assert not leaked, f"{path.name} импортирует {sorted(leaked)}"


@pytest.mark.parametrize("path", python_files(CORE), ids=lambda p: p.name)
def test_core_never_mentions_float(path):
    """float в денежном пути запрещён. Проверяет линтер, а не дисциплина."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "float"
    ]
    assert not offenders, f"{path.name}: float в строках {offenders}"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_file_is_longer_than_three_hundred_lines(path):
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= MAX_FILE_LINES, f"{path.name}: {lines} строк"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_only_the_calculator_multiplies(path):
    """Единственный источник истины — не лозунг, а проверяемое свойство.

    Умножение допускается в calculate.py (сам расчёт) и money.py (масштабирование
    Decimal). Больше нигде — ни в хранилище, ни в экспорте, ни в хендлерах.
    """
    if path.name in {"calculate.py", "money.py"}:
        return
    lines = _multiplication_lines(ast.parse(path.read_text(encoding="utf-8")))
    assert not lines, f"{path.name}: умножение в строках {lines}"


def test_handlers_do_not_compute_totals_themselves():
    """Хендлеры обязаны брать суммы из домена, а не суммировать строки сами."""
    for path in python_files(BOT):
        source = path.read_text(encoding="utf-8")
        assert "func.sum" not in source
        assert "TAX_RATE" not in source


def test_the_schema_holds_no_personal_field_but_the_one_it_must():
    """Доказательство схемой, а не обещанием (DoD Sprint 6a).

    user_id разрешён явным списком: он уже есть в positions, и история цен
    без него не отличила бы своё от чужого. Всё остальное — имя, телефон,
    почта, telegram-id, псевдоним автора — в базе не появляется. Спецификация
    price-radar предлагала HMAC от tg_user_id; это псевдонимизация, а не
    анонимность, и крауд всё равно живёт в 6b (ADR-017).
    """
    allowed = {"user_id"}
    forbidden = {"username", "user_name", "phone", "email", "tg_id", "telegram_id",
                 "first_name", "last_name", "full_name", "contributor_key"}
    found = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if column.name in forbidden or (column.name.endswith("_id")
                                        and column.name in forbidden - allowed)
    }
    assert not found, f"персональные поля в схеме: {sorted(found)}"


def test_price_history_stores_five_fields_and_no_sixth():
    """Цена — пять полей, а не документ. Разрастётся — заметим здесь."""
    columns = {column.name for column in PriceHistory.__table__.columns}
    assert columns == {"id", "user_id", "name_norm", "unit", "unit_spoken",
                       "price_kop", "observed_on"}


def test_the_monolith_is_gone():
    assert not (ROOT / "python3" / "webservice" / "telegram").exists()


def test_no_global_state_dicts_remain():
    """Состояние диалога живёт в таблице user_state, а не в памяти процесса."""
    for path in python_files(BOT, STORAGE):
        source = path.read_text(encoding="utf-8")
        assert "user_category" not in source
        assert "current_estimate_cache" not in source

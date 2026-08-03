"""Правила слоёв, проверяемые машиной, а не ревью (ADR-002, ADR-007)."""

from __future__ import annotations

import ast
import pathlib

import pytest

from conftest import CLOSED_TABLES
from smeta_storage import Base

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "packages" / "smeta_core"
PRICES = ROOT / "packages" / "smeta_prices"
STORAGE = ROOT / "packages" / "smeta_storage"
EXPORT = ROOT / "packages" / "smeta_export"
AI = ROOT / "packages" / "smeta_ai"
BOT = ROOT / "apps" / "bot"
API = ROOT / "apps" / "api"
SHARE = ROOT / "apps" / "share"

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
    # Публичная страница базу читает — иначе показывать нечего, — но напрямую
    # не разговаривает с ней ни строчкой: sqlalchemy здесь запрещён, и всё
    # общение идёт через smeta_storage.share (ADR-020).
    SHARE: {"telegram", "sqlalchemy", "openpyxl", "openai", "smeta_ai",
            "requests", "httpx", "aiohttp"},
}

# Что публичное приложение вправе взять из хранилища. Список закрыт: новая
# функция записи не появится здесь незаметно.
SHARE_MAY_IMPORT = {"share", "build_engine", "build_sessionmaker"}

# Глаголы записи SQLAlchemy. Без них apps/share не может сохранить ничего —
# ни отметку просмотра, ни согласование, ни тем более чужую смету. Обе
# разрешённые записи живут в smeta_storage.share и вызываются оттуда.
WRITE_VERBS = {"add", "add_all", "delete", "commit", "flush", "execute", "merge"}


def python_files(*roots: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for root in roots for path in root.rglob("*.py"))


ALL_FILES = python_files(CORE, PRICES, STORAGE, EXPORT, AI, BOT, API, SHARE)


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# Единицы вёрстки: «18 * mm» — это поле страницы, а не деньги. Список
# закрытый и проверяется по имени операнда, поэтому запрет на умножение денег
# остаётся в силе везде, включая генератор PDF.
LAYOUT_UNITS = {"mm", "cm", "inch"}


def _is_layout(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id in LAYOUT_UNITS


def _multiplication_lines(tree: ast.AST) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Mult)
        and not (_is_layout(node.left) or _is_layout(node.right))
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
    for layer in (CORE, PRICES, STORAGE, EXPORT, AI, BOT, API, SHARE):
        assert layer.is_dir(), f"нет слоя {layer}"
    assert len(ALL_FILES) > 15


@pytest.mark.parametrize("path", python_files(SHARE), ids=lambda p: p.name)
def test_the_public_app_takes_from_storage_only_what_is_listed(path):
    """Первый сервис, отдающий данные наружу без входа (ADR-020).

    Ограничение не в том, что он «старается» не писать, а в том, что писать
    ему нечем: доступ к хранилищу сведён к трём именам, и все они ведут в
    smeta_storage.share, где записей ровно две — отметка просмотра и статус
    согласования.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("smeta_storage"):
            leaked = {alias.name for alias in node.names} - SHARE_MAY_IMPORT
            assert not leaked, f"{path.name}: из хранилища взято лишнее — {sorted(leaked)}"


@pytest.mark.parametrize("path", python_files(SHARE), ids=lambda p: p.name)
def test_the_public_app_cannot_write_anything_by_itself(path):
    """Без commit/flush/execute изменение не переживёт запрос.

    Проверка синтаксическая, и этого достаточно: чтобы сохранить что-нибудь
    мимо smeta_storage.share, публичному приложению пришлось бы вызвать один
    из этих глаголов. Поведенческая пара к этому тесту — в test_share.py:
    там смета сравнивается до и после открытия страницы.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        f"{node.func.attr}() в строке {node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in WRITE_VERBS
    ]
    assert not offenders, f"{path.name}: запись из публичного приложения — {offenders}"


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


# Сериализовать слепок НЕ текущим форматом позволено ровно одному месту:
# check_integrity, которому надо сверить смету с тем, чем её замораживали.
# Старая версия формата — сверщик, а не калькулятор: выписать по ней новый
# документ должно быть невозможно, а не «не принято».
SNAPSHOT_FORMAT_INSIDERS = {"snapshot.py", "freeze.py"}


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_only_the_integrity_check_may_reach_an_older_snapshot_format(path):
    if path.name in SNAPSHOT_FORMAT_INSIDERS:
        return
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.keyword) and node.arg == "snapshot_format")
        or (isinstance(node, ast.Name) and node.id.startswith("_canonical_v"))
        # Импорт ловится отдельно от вызова: взять старый сериализатор себе —
        # уже нарушение, даже если строкой ниже его ещё не позвали.
        or (isinstance(node, ast.ImportFrom)
            and any(alias.name.startswith("_canonical_v") for alias in node.names))
    ]
    assert not offenders, f"{path.name}: старый формат слепка в строках {offenders}"


def test_handlers_do_not_compute_totals_themselves():
    """Хендлеры обязаны брать суммы из домена, а не суммировать строки сами."""
    for path in python_files(BOT):
        source = path.read_text(encoding="utf-8")
        assert "func.sum" not in source
        assert "TAX_RATE" not in source


@pytest.mark.parametrize("table_name", sorted(CLOSED_TABLES))
def test_a_closed_table_holds_exactly_the_fields_it_was_designed_for(table_name):
    """Белый список там, где состав полей закрыт по замыслу.

    Две таблицы существуют ради того, чтобы хранить меньше: история цен — это
    цена, пережившая свою смету, а не документ (ADR-017); публичная ссылка
    хранит только доступ и ни слова о том, кто её открыл (ADR-020 §8). Для них
    вопрос не «не пролезло ли запрещённое», а «ровно ли то, о чём договорились»,
    и отвечает на него сравнение множеств.

    Новое поле здесь — решение, а не побочный эффект правки соседнего кода.
    """
    table = Base.metadata.tables[table_name]
    assert {column.name for column in table.columns} == CLOSED_TABLES[table_name]


def test_the_schema_holds_no_personal_field_but_the_one_it_must():
    """Доказательство схемой, а не обещанием (DoD Sprint 6a).

    user_id разрешён явно: он уже есть в positions, и история цен без него не
    отличила бы своё от чужого. Всё остальное — имя, телефон, почта,
    telegram-id, псевдоним автора — в базе не появляется. Спецификация
    price-radar предлагала HMAC от tg_user_id; это псевдонимизация, а не
    анонимность, и крауд всё равно живёт в 6b (ADR-017).

    Здесь именно чёрный список, и это не недоделанный белый. Состав остальных
    таблиц открыт по замыслу: `estimates` только за этот спринт получила две
    новые колонки, `positions` и состояние диалога растут с каждой возможностью.
    Белый список там пришлось бы дописывать на каждой фиче, его красный цвет
    означал бы «ты добавил колонку» — то есть ничего, — и правился бы он не
    глядя. Чёрный отвечает на другой вопрос, который с ростом таблицы не
    протухает: не пролезло ли персональное.

    Цена честная и названа прямо: `customer_name` этот список пропустит.
    Поэтому у двух таблиц, где состав закрыт, проверка белая — тестом выше.
    """
    forbidden = {"username", "user_name", "phone", "email", "tg_id", "telegram_id",
                 "first_name", "last_name", "full_name", "contributor_key",
                 "customer_name", "client_name", "client_phone", "contact"}
    found = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if column.name in forbidden
    }
    assert not found, f"персональные поля в схеме: {sorted(found)}"


def test_the_monolith_is_gone():
    assert not (ROOT / "python3" / "webservice" / "telegram").exists()


def test_no_global_state_dicts_remain():
    """Состояние диалога живёт в таблице user_state, а не в памяти процесса."""
    for path in python_files(BOT, STORAGE):
        source = path.read_text(encoding="utf-8")
        assert "user_category" not in source
        assert "current_estimate_cache" not in source

"""Правила слоёв, проверяемые машиной, а не ревью (ADR-002, ADR-007)."""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "packages" / "smeta_core"
STORAGE = ROOT / "packages" / "smeta_storage"
EXPORT = ROOT / "packages" / "smeta_export"
BOT = ROOT / "apps" / "bot"
API = ROOT / "apps" / "api"

MAX_FILE_LINES = 300

# Что каждому слою запрещено импортировать (конституция, правило 1).
FORBIDDEN = {
    CORE: {"telegram", "sqlalchemy", "openpyxl", "requests", "httpx",
           "aiohttp", "fastapi", "pydantic", "dotenv"},
    STORAGE: {"telegram", "openpyxl", "requests", "httpx", "aiohttp", "fastapi", "dotenv"},
    EXPORT: {"telegram", "sqlalchemy", "requests", "httpx", "aiohttp", "fastapi", "dotenv"},
    BOT: {"sqlalchemy", "openpyxl"},
    # API без состояния: базы он не касается вовсе (ADR-008).
    API: {"telegram", "sqlalchemy", "openpyxl", "smeta_storage"},
}


def python_files(*roots: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path for root in roots for path in root.rglob("*.py"))


ALL_FILES = python_files(CORE, STORAGE, EXPORT, BOT, API)


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


def test_every_layer_is_present():
    for layer in (CORE, STORAGE, EXPORT, BOT, API):
        assert layer.is_dir(), f"нет слоя {layer}"
    assert len(ALL_FILES) > 15


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


def test_the_monolith_is_gone():
    assert not (ROOT / "python3" / "webservice" / "telegram").exists()


def test_no_global_state_dicts_remain():
    """Состояние диалога живёт в таблице user_state, а не в памяти процесса."""
    for path in python_files(BOT, STORAGE):
        source = path.read_text(encoding="utf-8")
        assert "user_category" not in source
        assert "current_estimate_cache" not in source

"""Правила слоёв, проверяемые машиной, а не ревью (ADR-002, ADR-003)."""

from __future__ import annotations

import ast
import pathlib

import pytest

CORE_DIR = pathlib.Path(__file__).resolve().parent.parent / "packages" / "smeta_core"
CORE_FILES = sorted(CORE_DIR.glob("*.py"))

# Ядро — чистый домен. Всё, что относится к транспорту, хранению или отчётам,
# импортировать запрещено (конституция, правило 1).
FORBIDDEN_ROOTS = {
    "telegram", "sqlalchemy", "openpyxl", "requests", "httpx",
    "aiohttp", "urllib", "fastapi", "pydantic", "dotenv",
}


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_package_is_not_empty():
    assert CORE_FILES, "ядро не найдено — проверь путь"


@pytest.mark.parametrize("path", CORE_FILES, ids=lambda p: p.name)
def test_core_imports_nothing_external(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    leaked = _imported_roots(tree) & FORBIDDEN_ROOTS
    assert not leaked, f"{path.name} импортирует {sorted(leaked)} — ядро должно быть чистым"


@pytest.mark.parametrize("path", CORE_FILES, ids=lambda p: p.name)
def test_core_never_mentions_float(path):
    """float в денежном пути запрещён. Здесь это проверяет линтер, а не дисциплина."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "float"
    ]
    assert not offenders, f"{path.name}: float в строках {offenders}"


@pytest.mark.parametrize("path", CORE_FILES, ids=lambda p: p.name)
def test_core_files_are_under_three_hundred_lines(path):
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= 300, f"{path.name}: {lines} строк"


def test_only_calculate_module_multiplies_money():
    """Единственный источник истины — не лозунг, а проверяемое свойство.

    Умножение Decimal-значений допускается только в calculate.py; в остальных
    модулях ядра денежной арифметики нет (конвертация масштаба использует
    scaleb, а не умножение).
    """
    for path in CORE_FILES:
        if path.name in {"calculate.py", "money.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        multiplications = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
        ]
        assert not multiplications, f"{path.name}: умножение в строках {multiplications}"

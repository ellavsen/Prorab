"""Артефакты, которые лежат в репозитории, обязаны совпадать с кодом.

Схема и векторы сходимости — публичные обещания. Если они разъедутся с кодом,
об этом узнает потребитель, а не автор. Здесь это ловится сборкой.
"""

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIDGE_DIR = ROOT / "apps" / "web" / "public" / "py"

sys.path.insert(0, str(ROOT / "scripts"))


def test_openapi_json_matches_the_code():
    from export_openapi import TARGET, render

    assert TARGET.exists(), "docs/openapi.json отсутствует"
    assert TARGET.read_text(encoding="utf-8") == render(), (
        "docs/openapi.json устарел — выполни python scripts/export_openapi.py"
    )


def test_openapi_declares_every_route():
    schema = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert set(schema["paths"]) == {"/healthz", "/units", "/calculate", "/xlsx", "/parse"}


def test_openapi_documents_money_as_strings():
    """В схеме деньги должны быть строками, иначе клиент сгенерирует float."""
    schema = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    totals = schema["components"]["schemas"]["TotalsOut"]["properties"]
    for field in ("subtotal", "markup", "total"):
        assert totals[field]["type"] == "string", f"{field} описано не строкой"


@pytest.fixture(scope="module")
def bridge():
    sys.path.insert(0, str(BRIDGE_DIR))
    import bridge as module

    return module


def test_conformance_vectors_match_current_core(bridge):
    """Векторы для браузера считаются CPython — они не должны отстать от ядра."""
    vectors = json.loads((ROOT / "tests" / "vectors" / "conformance.json").read_text("utf-8"))

    for case in vectors["calculate"]:
        actual = json.loads(bridge.calculate(json.dumps(case["request"])))
        assert actual == case["expected"], (
            f"вектор «{case['name']}» разошёлся с ядром — "
            f"обнови: python scripts/make_conformance.py"
        )

    for case in vectors["parse"]:
        actual = json.loads(bridge.parse_lines(json.dumps(case["request"])))
        assert actual == case["expected"]


def test_bridge_uses_the_same_calculator_as_everything_else(bridge):
    """Мост для браузера не считает сам, а зовёт домен."""
    source = (BRIDGE_DIR / "bridge.py").read_text(encoding="utf-8")
    assert "calculate_estimate" in source
    assert "build_workbook" in source

    import ast

    multiplications = [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
    ]
    assert not multiplications, f"в мосте появилось умножение: строки {multiplications}"


def test_installed_distribution_is_importable():
    """Ловит молчаливо сломанную установку.

    На macOS Python 3.13+ пропускает .pth с флагом hidden, и `pip install -e .`
    может «пройти», оставив пакеты неимпортируемыми. Тесты этого не замечают —
    им путь задаёт pythonpath из pyproject.toml. Здесь проверяется именно
    установка: чистый процесс, нейтральный каталог, без pythonpath.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import smeta_core, smeta_storage, smeta_export, bot, api"],
        cwd=ROOT.parent,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, (
        "установленный пакет не импортируется:\n"
        f"{result.stderr}\n"
        "на macOS помогает: chflags -R nohidden .venv && pip install -e ."
    )

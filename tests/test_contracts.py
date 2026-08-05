"""Артефакты, которые лежат в репозитории, обязаны совпадать с кодом.

Схема и векторы сходимости — публичные обещания. Если они разъедутся с кодом,
об этом узнает потребитель, а не автор. Здесь это ловится сборкой.
"""

import fnmatch
import json
import pathlib
import subprocess
import sys
import tomllib

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
    assert set(schema["paths"]) == {"/healthz", "/units", "/catalog/lookup",
                                   "/calculate", "/xlsx", "/parse"}


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


def test_the_browser_demo_does_not_need_the_pdf_dependency():
    """Демо на Pyodide ставит колёса руками: openpyxl есть, reportlab нет.

    Дефект, который этот тест закрывает, прожил два коммита и был невидим:
    smeta_export.__init__ импортировал .pdf на уровне модуля, а тот —
    reportlab. В боте и тестах это ничего не ломало, потому что reportlab там
    стоит. В браузере демо просто не поднялось бы, и узнали бы мы об этом от
    того, кто открыл ссылку.

    Проверяется в отдельном процессе с заглушкой вместо reportlab: внутри
    текущего он уже импортирован другими тестами.
    """
    guard = (
        "import sys;"
        "sys.modules['reportlab'] = None;"
        "from smeta_export import build_workbook, build_page, DocumentMeta;"
        "assert 'smeta_export.pdf' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", guard], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, (
        "smeta_export тянет reportlab при импорте — демо на Pyodide не поднимется:\n"
        f"{result.stderr}"
    )


def test_the_pdf_generator_is_still_reachable_the_usual_way():
    """Ленивость не должна стоить читаемости на стороне вызывающего."""
    from smeta_export import build_pdf

    assert callable(build_pdf)


def test_installed_distribution_is_importable():
    """Ловит молчаливо сломанную установку.

    На macOS Python 3.13+ пропускает .pth с флагом hidden, и `pip install -e .`
    может «пройти», оставив пакеты неимпортируемыми. Тесты этого не замечают —
    им путь задаёт pythonpath из pyproject.toml. Здесь проверяется именно
    установка: чистый процесс, нейтральный каталог, без pythonpath.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import smeta_core, smeta_storage, smeta_export, bot, api, share"],
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


def test_every_runtime_asset_is_declared_as_package_data():
    """Ловит установку, которая молча приехала без данных.

    Соседний тест проверяет, что установленное импортируется. Этот — что оно
    ещё и укомплектовано: setuptools кладёт в колесо только .py, а всё
    остальное — ровно то, что перечислено в package-data. Незаявленный файл
    исчезает без единого предупреждения, и узнать об этом можно только в
    рантайме — причём не здесь, где путь задаёт pythonpath и исходное дерево
    на месте, а в контейнере, собранном через `pip install .` (docs/deploy.md).

    Так уже случалось со шрифтом PDF: он лежит в репозитории намеренно
    (ADR-021), но в колесо не попадал.
    """
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = declared["tool"]["setuptools"]["package-data"]

    undeclared = []
    for path in sorted((ROOT / "packages").rglob("*")):
        if not path.is_file() or path.suffix == ".py":
            continue
        relative = path.relative_to(ROOT / "packages")
        package, tail = relative.parts[0], "/".join(relative.parts[1:])
        if package.endswith(".egg-info") or "__pycache__" in relative.parts:
            continue
        if not any(fnmatch.fnmatch(tail, glob) for glob in patterns.get(package, [])):
            undeclared.append(str(relative))

    assert not undeclared, (
        "файлы лежат в пакете, но не поедут в установку — допиши их в "
        "[tool.setuptools.package-data] в pyproject.toml:\n  " + "\n  ".join(undeclared)
    )

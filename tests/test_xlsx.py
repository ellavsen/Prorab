"""Группа E: XLSX с живыми формулами (docs/money.md §6.E)."""

from __future__ import annotations

import io
import re
import shutil
from decimal import Decimal as D

import pytest
from openpyxl import Workbook, load_workbook

from smeta_core import Category, PositionData, calculate_estimate

from conftest import excel_round
from test_migration import load_bot

POSITIONS = [
    PositionData(Category.WORK, "Побелка", D("1.5"), D("100.10")),
    PositionData(Category.WORK, "Стяжка", D("2.5"), D("100.10")),
    PositionData(Category.WORK, "Копейка", D("1"), D("0.01")),
    PositionData(Category.WORK, "Половинка", D("0.5"), D("0.01")),   # ровно 0.005
    PositionData(Category.WORK, "Максимум", D("99999.999"), D("5000.00")),
]
RATE = D("6.00")


@pytest.fixture
def sheet(tmp_path, monkeypatch):
    bot = load_bot(tmp_path / "xlsx.db", monkeypatch)
    workbook = Workbook()
    bot.build_sheet(workbook.active, "Работы", POSITIONS, RATE, is_work=True)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return load_workbook(buffer).active


def test_e4_row_formulas_reference_the_rate_cell_not_a_literal(sheet):
    for row in range(4, 4 + len(POSITIONS)):
        formula = sheet[f"F{row}"].value
        assert "$B$1" in formula, formula
        assert "1.06" not in formula and "6.00" not in formula, formula


def test_e5_totals_are_sums_over_rounded_cells(sheet):
    last = 3 + len(POSITIONS)
    assert sheet[f"E{last + 1}"].value == f"=SUM(E4:E{last})"
    assert sheet[f"F{last + 1}"].value == f"=SUM(F4:F{last})"


def test_markup_row_is_a_difference(sheet):
    last = 3 + len(POSITIONS)
    assert sheet[f"F{last + 2}"].value == f"=F{last + 1}-E{last + 1}"


def test_e6_quantity_and_price_cells_round_trip_exactly(sheet):
    for index, position in enumerate(POSITIONS):
        row = 4 + index
        assert D(str(sheet[f"C{row}"].value)) == position.qty
        assert D(str(sheet[f"D{row}"].value)) == position.price


def test_rate_cell_holds_the_rate(sheet):
    assert D(str(sheet["B1"].value)) == RATE


def test_formulas_transcribe_the_domain_exactly(sheet):
    """Считаем формулы из файла по правилам Excel и сверяем с ядром.

    Это не второй вычислитель, а проверка транскрипции: формулы обязаны быть
    именно =ROUND(C*D,2) и =ROUND(E*(1+$B$1/100),2), и давать те же копейки.
    """
    expected = calculate_estimate(POSITIONS, RATE, RATE)
    rate = float(sheet["B1"].value)

    excel_subtotal = D("0.00")
    excel_total = D("0.00")
    for index, line in enumerate(expected.lines):
        row = 4 + index
        assert sheet[f"E{row}"].value == f"=ROUND(C{row}*D{row},2)"
        assert sheet[f"F{row}"].value == f"=ROUND(E{row}*(1+$B$1/100),2)"

        base = excel_round(float(sheet[f"C{row}"].value) * float(sheet[f"D{row}"].value))
        total = excel_round(float(base) * (1.0 + rate / 100.0))
        assert base == line.base
        assert total == line.total
        excel_subtotal += base
        excel_total += total

    assert excel_subtotal == expected.subtotal
    assert excel_total == expected.total
    assert excel_total - excel_subtotal == expected.markup


def test_empty_sheet_still_generates(tmp_path, monkeypatch):
    bot = load_bot(tmp_path / "empty.db", monkeypatch)
    workbook = Workbook()
    bot.build_sheet(workbook.active, "Работы", [], RATE, is_work=True)
    buffer = io.BytesIO()
    workbook.save(buffer)
    assert buffer.getbuffer().nbytes > 0


@pytest.mark.skipif(
    shutil.which("soffice") is None,
    reason="LibreOffice не установлен — пересчёт формул проверить нечем",
)
def test_e1_libreoffice_recalculation_matches(tmp_path, monkeypatch):
    """E1: пересчёт headless LibreOffice. Запускается только там, где он есть."""
    import subprocess

    bot = load_bot(tmp_path / "lo.db", monkeypatch)
    workbook = Workbook()
    bot.build_sheet(workbook.active, "Работы", POSITIONS, RATE, is_work=True)
    source = tmp_path / "estimate.xlsx"
    workbook.save(source)

    subprocess.run(
        ["soffice", "--headless", "--convert-to", "xlsx", "--outdir",
         str(tmp_path / "out"), str(source)],
        check=True, capture_output=True, timeout=180,
    )
    recalculated = load_workbook(tmp_path / "out" / "estimate.xlsx", data_only=True).active
    expected = calculate_estimate(POSITIONS, RATE, RATE)

    for index, line in enumerate(expected.lines):
        row = 4 + index
        assert D(str(recalculated[f"E{row}"].value)) == line.base
        assert D(str(recalculated[f"F{row}"].value)) == line.total

    last = 3 + len(POSITIONS)
    assert D(str(recalculated[f"F{last + 1}"].value)) == expected.total
    assert D(str(recalculated[f"E{last + 1}"].value)) == expected.subtotal


def test_no_arithmetic_left_in_the_rendering_layer():
    """В слое отображения не должно остаться умножения денег (ADR-002)."""
    import ast
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "python3" / "webservice" / "telegram" / "main_agent.py"
    ).read_text(encoding="utf-8")

    # Денежных SQL-агрегатов быть не должно ни в каком виде.
    assert "func.sum" not in source
    assert not re.search(r"\bTAX_RATE\b", source)
    assert "sum_line_with_tax" not in source

    tree = ast.parse(source)
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "calculate_estimate" in calls

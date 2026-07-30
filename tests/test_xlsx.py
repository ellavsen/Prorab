"""Группа E: XLSX с живыми формулами (docs/money.md §6.E)."""

from __future__ import annotations

import io
import shutil
from decimal import Decimal as D

import pytest
from openpyxl import Workbook, load_workbook

from conftest import excel_round
from smeta_core import Category, PositionData, calculate_estimate
from smeta_export import FIRST_DATA_ROW, build_sheet, build_workbook

POSITIONS = [
    PositionData(Category.WORK, "Побелка", D("1.5"), D("100.10"), "м²"),
    PositionData(Category.WORK, "Стяжка", D("2.5"), D("100.10"), "м²"),
    PositionData(Category.WORK, "Копейка", D("1"), D("0.01"), "шт"),
    PositionData(Category.WORK, "Половинка", D("0.5"), D("0.01"), "шт"),   # ровно 0.005
    PositionData(Category.WORK, "Максимум", D("99999.999"), D("5000.00"), "м.п."),
]
RATE = D("6.00")
LAST_DATA_ROW = FIRST_DATA_ROW + len(POSITIONS) - 1


@pytest.fixture
def sheet():
    workbook = Workbook()
    build_sheet(workbook.active, "Работы", POSITIONS, RATE, is_work=True)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return load_workbook(buffer).active


def test_e4_row_formulas_reference_the_rate_cell_not_a_literal(sheet):
    for row in range(FIRST_DATA_ROW, LAST_DATA_ROW + 1):
        formula = sheet[f"G{row}"].value
        assert "$B$1" in formula, formula
        assert "1.06" not in formula
        assert "6.00" not in formula


def test_e5_totals_are_sums_over_rounded_cells(sheet):
    total_row = LAST_DATA_ROW + 1
    assert sheet[f"F{total_row}"].value == f"=SUM(F{FIRST_DATA_ROW}:F{LAST_DATA_ROW})"
    assert sheet[f"G{total_row}"].value == f"=SUM(G{FIRST_DATA_ROW}:G{LAST_DATA_ROW})"


def test_markup_row_is_a_difference(sheet):
    total_row = LAST_DATA_ROW + 1
    assert sheet[f"G{total_row + 1}"].value == f"=G{total_row}-F{total_row}"


def test_e6_quantity_and_price_cells_round_trip_exactly(sheet):
    for index, position in enumerate(POSITIONS):
        row = FIRST_DATA_ROW + index
        assert D(str(sheet[f"D{row}"].value)) == position.qty
        assert D(str(sheet[f"E{row}"].value)) == position.price


def test_unit_column_carries_the_unit(sheet):
    for index, position in enumerate(POSITIONS):
        assert sheet[f"C{FIRST_DATA_ROW + index}"].value == position.unit


def test_missing_unit_is_shown_as_a_dash():
    workbook = Workbook()
    build_sheet(
        workbook.active, "Работы",
        [PositionData(Category.WORK, "Без единицы", D("1"), D("1.00"))],
        RATE, is_work=True,
    )
    assert workbook.active[f"C{FIRST_DATA_ROW}"].value == "—"


def test_rate_cell_holds_the_rate(sheet):
    assert D(str(sheet["B1"].value)) == RATE


def test_formulas_transcribe_the_domain_exactly(sheet):
    """Считаем формулы из файла по правилам Excel и сверяем с ядром.

    Это не второй вычислитель, а проверка транскрипции: формулы обязаны быть
    именно =ROUND(D*E,2) и =ROUND(F*(1+$B$1/100),2) и давать те же копейки.
    """
    expected = calculate_estimate(POSITIONS, RATE, RATE)
    rate = float(sheet["B1"].value)

    excel_subtotal = D("0.00")
    excel_total = D("0.00")
    for index, line in enumerate(expected.lines):
        row = FIRST_DATA_ROW + index
        assert sheet[f"F{row}"].value == f"=ROUND(D{row}*E{row},2)"
        assert sheet[f"G{row}"].value == f"=ROUND(F{row}*(1+$B$1/100),2)"

        base = excel_round(float(sheet[f"D{row}"].value) * float(sheet[f"E{row}"].value))
        total = excel_round(float(base) * (1.0 + rate / 100.0))
        assert base == line.base
        assert total == line.total
        excel_subtotal += base
        excel_total += total

    assert excel_subtotal == expected.subtotal
    assert excel_total == expected.total
    assert excel_total - excel_subtotal == expected.markup


def test_empty_sheet_still_generates():
    buffer = build_workbook([], [], RATE, RATE)
    assert buffer.getbuffer().nbytes > 0


def test_workbook_has_both_sheets():
    book = load_workbook(build_workbook(POSITIONS[:1], POSITIONS[1:], RATE, D("0.00")))
    assert book.sheetnames == ["Работы", "Материалы и расходники"]
    assert D(str(book["Материалы и расходники"]["B1"].value)) == D("0.00")


@pytest.mark.skipif(
    shutil.which("soffice") is None,
    reason="LibreOffice не установлен — пересчёт формул проверить нечем",
)
def test_e1_libreoffice_recalculation_matches(tmp_path):
    """E1: пересчёт headless LibreOffice. Запускается только там, где он есть."""
    import subprocess

    workbook = Workbook()
    build_sheet(workbook.active, "Работы", POSITIONS, RATE, is_work=True)
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
        row = FIRST_DATA_ROW + index
        assert D(str(recalculated[f"F{row}"].value)) == line.base
        assert D(str(recalculated[f"G{row}"].value)) == line.total

    total_row = LAST_DATA_ROW + 1
    assert D(str(recalculated[f"F{total_row}"].value)) == expected.subtotal
    assert D(str(recalculated[f"G{total_row}"].value)) == expected.total

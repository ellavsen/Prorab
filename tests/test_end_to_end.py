"""Сходимость каналов на живой базе, а не только в ядре."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from conftest import excel_round, open_storage
from smeta_core import Category, calculate_estimate, default_unit, parse_position_line
from smeta_export import FIRST_DATA_ROW, build_workbook
from smeta_storage import (
    Estimate,
    Position,
    create_estimate,
    positions,
    verified_totals,
)

UID = 42
INPUT_LINES = [
    (Category.WORK, "Побелка, 1.5 м2, 100.10"),
    (Category.WORK, "Стяжка, 2.5 м2, 100.10"),
    (Category.WORK, "Половинка, 0.5, 0.01"),
    (Category.MATERIAL, "Гвозди, 1000 шт, 0.37"),
    (Category.MATERIAL, "Подарок, 3, 0"),
]


@pytest.fixture
def storage(tmp_path):
    _, Session = open_storage(tmp_path / "e2e.db")
    with Session() as db:
        estimate = create_estimate(db, UID, name="Смета №1")
        for category, line in INPUT_LINES:
            position = parse_position_line(line, category)
            if not position.unit:
                position = replace(position, unit=default_unit(category.value))
            positions.add(db, UID, estimate.id, position)
        db.commit()
        estimate_id = estimate.id
    return Session, estimate_id


def test_new_estimate_gets_the_default_markup(storage):
    Session, estimate_id = storage
    with Session() as db:
        estimate = db.get(Estimate, estimate_id)
        assert estimate.markup_work_bp == 600
        assert estimate.markup_material_rate == D("6.00")


def test_units_are_stored_not_discarded(storage):
    Session, estimate_id = storage
    with Session() as db:
        rows = {r.name: r.unit for r in positions.load(db, UID, estimate_id)}
    assert rows["Побелка"] == "м²"
    assert rows["Гвозди"] == "шт"
    # Единица не указана — подставлена по категории (ADR-006).
    assert rows["Половинка"] == "м²"
    assert rows["Подарок"] == "шт"


def test_all_three_channels_agree_on_a_real_database(storage):
    Session, estimate_id = storage
    with Session() as db:
        estimate = db.get(Estimate, estimate_id)
        rows = positions.load(db, UID, estimate_id)
        listing = calculate_estimate(
            [r.to_domain() for r in rows],
            estimate.markup_work_rate,
            estimate.markup_material_rate,
        )
        summary = verified_totals(db, estimate)
        materials, works = positions.by_category(db, UID, estimate_id)
        work_rate = estimate.markup_work_rate
        material_rate = estimate.markup_material_rate

    assert sum(line.total for line in listing.lines) == listing.total
    assert summary.total == listing.total
    assert len(materials) + len(works) == len(INPUT_LINES)

    book = load_workbook(build_workbook(materials, works, work_rate, material_rate))
    excel_total = D("0.00")
    for sheet in book.worksheets:
        rate = float(sheet["B1"].value)
        row = FIRST_DATA_ROW
        while sheet[f"D{row}"].value is not None:
            base = excel_round(float(sheet[f"D{row}"].value) * float(sheet[f"E{row}"].value))
            excel_total += excel_round(float(base) * (1.0 + rate / 100.0))
            row += 1

    assert excel_total == listing.total


def test_export_does_not_re_merge_duplicates(storage):
    """Склейка меняет итог, поэтому она бывает только при вводе.

    Две строки по 0.5 × 0.01 дают 0.02; склеенные в 1.0 × 0.01 дали бы 0.01.
    Если экспорт начнёт склеивать, этот тест упадёт — и правильно сделает.
    """
    Session, estimate_id = storage
    with Session() as db:
        estimate = db.get(Estimate, estimate_id)
        db.add(Position(
            user_id=UID, estimate_id=estimate_id, category="work",
            name="Половинка-2", unit="шт", qty_milli=500, price_kop=1,
        ))
        db.commit()

        rows = positions.load(db, UID, estimate_id)
        listing = calculate_estimate(
            [r.to_domain() for r in rows],
            estimate.markup_work_rate,
            estimate.markup_material_rate,
        )
        materials, works = positions.by_category(db, UID, estimate_id)
        exported = calculate_estimate(
            works + materials, estimate.markup_work_rate, estimate.markup_material_rate
        )

    assert exported.total == listing.total
    assert len(works) + len(materials) == len(rows)


def test_adding_a_duplicate_line_merges_before_rounding(storage):
    """При вводе дубль складывается в существующую строку — до расчёта."""
    Session, estimate_id = storage
    with Session() as db:
        position = parse_position_line("Гвозди, 500 шт, 0.37", Category.MATERIAL)
        positions.add(db, UID, estimate_id, position)
        db.commit()
        rows = positions.load(db, UID, estimate_id)

    nails = [r for r in rows if r.name == "Гвозди"]
    assert len(nails) == 1
    assert nails[0].qty == D("1500")

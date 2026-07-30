"""Сходимость каналов на живой базе, а не только в ядре.

Проверяется тот же код, который вызывают хендлеры: загрузка позиций, расчёт
и сборка XLSX.
"""

from __future__ import annotations

import io
from decimal import Decimal as D

import pytest
from openpyxl import Workbook, load_workbook

from smeta_core import Category, calculate_estimate, parse_position_line, to_kop, to_milli

from conftest import excel_round
from test_migration import load_bot

INPUT_LINES = [
    (Category.WORK, "Побелка, 1.5, 100.10"),
    (Category.WORK, "Стяжка, 2.5, 100.10"),
    (Category.WORK, "Половинка, 0.5, 0.01"),
    (Category.MATERIAL, "Гвозди, 1000, 0.37"),
    (Category.MATERIAL, "Подарок, 3, 0"),
]


@pytest.fixture
def bot_with_estimate(tmp_path, monkeypatch):
    bot = load_bot(tmp_path / "e2e.db", monkeypatch)
    uid = 42
    with bot.SessionLocal() as db:
        estimate = bot.Estimate(user_id=uid, number=1, name="Смета №1")
        db.add(estimate)
        db.commit()
        db.refresh(estimate)
        for category, line in INPUT_LINES:
            position = parse_position_line(line, category)
            db.add(bot.Position(
                user_id=uid,
                estimate_id=estimate.id,
                category=category.value,
                name=position.name,
                qty_milli=to_milli(position.qty),
                price_kop=to_kop(position.price),
                unit="",
            ))
        db.commit()
        estimate_id = estimate.id
    return bot, uid, estimate_id


def test_new_estimate_gets_the_default_markup(bot_with_estimate):
    bot, _, estimate_id = bot_with_estimate
    with bot.SessionLocal() as db:
        estimate = db.get(bot.Estimate, estimate_id)
        assert estimate.markup_work_bp == 600
        assert estimate.markup_material_rate == D("6.00")


def test_all_three_channels_agree_on_a_real_database(bot_with_estimate):
    bot, uid, estimate_id = bot_with_estimate
    with bot.SessionLocal() as db:
        estimate = db.get(bot.Estimate, estimate_id)

        # Канал /list: строки и итог из одного расчёта.
        rows = bot.load_positions(db, uid, estimate_id)
        listing = calculate_estimate(
            [r.to_domain() for r in rows],
            estimate.markup_work_rate,
            estimate.markup_material_rate,
        )
        # Канал /estimates.
        summary = bot.estimate_totals(db, uid, estimate)
        # Канал XLSX.
        materials, works = bot.positions_by_category(db, uid, estimate_id)

    assert sum(line.total for line in listing.lines) == listing.total
    assert summary.total == listing.total
    assert len(materials) + len(works) == len(INPUT_LINES)

    workbook = Workbook()
    bot.build_sheet(workbook.active, "Работы", works, estimate.markup_work_rate, is_work=True)
    bot.build_sheet(
        workbook.create_sheet(), "Материалы", materials,
        estimate.markup_material_rate, is_work=False,
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    book = load_workbook(buffer)

    excel_total = D("0.00")
    for sheet in book.worksheets:
        rate = float(sheet["B1"].value)
        row = 4
        while sheet[f"C{row}"].value is not None:
            base = excel_round(float(sheet[f"C{row}"].value) * float(sheet[f"D{row}"].value))
            excel_total += excel_round(float(base) * (1.0 + rate / 100.0))
            row += 1

    assert excel_total == listing.total


def test_export_does_not_re_merge_duplicates(bot_with_estimate):
    """Склейка меняет итог, поэтому она бывает только при вводе.

    Две строки по 0.5 × 0.01 дают 0.02; склеенные в 1.0 × 0.01 дали бы 0.01.
    Если экспорт начнёт склеивать, этот тест упадёт — и правильно сделает.
    """
    bot, uid, estimate_id = bot_with_estimate
    with bot.SessionLocal() as db:
        estimate = db.get(bot.Estimate, estimate_id)
        db.add(bot.Position(
            user_id=uid, estimate_id=estimate_id, category="Работа",
            name="Половинка", qty_milli=500, price_kop=1, unit="",
        ))
        db.commit()

        rows = bot.load_positions(db, uid, estimate_id)
        listing = calculate_estimate(
            [r.to_domain() for r in rows],
            estimate.markup_work_rate,
            estimate.markup_material_rate,
        )
        materials, works = bot.positions_by_category(db, uid, estimate_id)

    exported = calculate_estimate(
        works + materials, estimate.markup_work_rate, estimate.markup_material_rate
    )
    assert exported.total == listing.total
    assert len(works) + len(materials) == len(rows)


def test_adding_a_duplicate_line_merges_before_rounding(bot_with_estimate):
    """При вводе дубль складывается в существующую строку — до расчёта."""
    bot, uid, estimate_id = bot_with_estimate
    with bot.SessionLocal() as db:
        position = parse_position_line("Гвозди, 500, 0.37", Category.MATERIAL)
        existing = db.execute(
            bot.select(bot.Position).where(
                bot.Position.estimate_id == estimate_id,
                bot.Position.name == "Гвозди",
                bot.Position.price_kop == to_kop(position.price),
            )
        ).scalars().first()
        merged = bot.merge_duplicates([existing.to_domain(), position])[0]
        existing.qty_milli = to_milli(merged.qty)
        db.commit()

        rows = bot.load_positions(db, uid, estimate_id)

    assert len([r for r in rows if r.name == "Гвозди"]) == 1
    assert next(r for r in rows if r.name == "Гвозди").qty == D("1500")

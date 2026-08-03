"""PDF-документ: числа те же, кириллица читается, лишнего в файле нет.

Проверяется не «файл сгенерировался», а то, что из него можно вынуть текст
обратно и он совпадает с расчётом домена. PDF, который открывается, но врёт
в сумме, хуже отсутствующего.
"""

import io
import os
from datetime import date
from decimal import Decimal as D

import pytest
from pypdf import PdfReader
from sqlalchemy import text
from test_document_naming import UID, FakeDocumentMessage, FakeUpdate

from conftest import ErrorContext, ErrorUpdate, async_test, open_storage
from smeta_core import (
    Category,
    IntegrityError,
    PositionData,
    calculate_estimate,
    format_money,
)
from smeta_export import DocumentMeta, build_pdf
from smeta_export.pdf import FONT_PATH, printable
from smeta_storage import create_estimate, positions, send, set_current_estimate

RATE = D("6.00")
TODAY = date(2026, 8, 3)


def meta(**kwargs) -> DocumentMeta:
    base = dict(number=3, version=2, title="Ремонт на объекте", on=TODAY,
                work_rate=RATE, material_rate=RATE, status="Отправлена заказчику")
    return DocumentMeta(**{**base, **kwargs})


def rows():
    return [
        PositionData(Category.WORK, "Побелка потолка", D("150"), D("3000"), unit="м²"),
        PositionData(Category.WORK, "Стяжка", D("40.5"), D("700"), unit="м²"),
        PositionData(Category.MATERIAL, "Цемент М500", D("20"), D("380"),
                     unit="", unit_spoken="мешков"),
    ]


def rendered(positions=None, document=None):
    positions = rows() if positions is None else positions
    totals = calculate_estimate(positions, RATE, RATE)
    buffer = build_pdf(totals, document or meta())
    return totals, PdfReader(io.BytesIO(buffer.getvalue()))


def text_of(reader) -> str:
    return "\n".join(page.extract_text() for page in reader.pages).replace("\xa0", " ")


# --- Числа ---


def test_every_number_in_the_document_comes_from_the_domain():
    """DoD: суммы в PDF совпадают с calculate_estimate до копейки."""
    totals, reader = rendered()
    text = text_of(reader)

    for line in totals.lines:
        assert format_money(line.total) in text, line.position.name
        assert format_money(line.position.price) in text
    assert format_money(totals.total) in text
    assert format_money(totals.markup) in text
    assert format_money(totals.subtotal) in text


def test_the_section_totals_add_up_to_the_document_total():
    """Промежуточные итоги считает домен, а не генератор."""
    totals, reader = rendered()
    text = text_of(reader)

    works = sum((line.total for line in totals.lines
                 if line.position.category == Category.WORK), D("0.00"))
    materials = totals.total - works
    assert format_money(works) in text
    assert format_money(materials) in text


def test_money_is_formatted_the_one_way_the_project_formats_money():
    """Запятая как разделитель и две цифры — иначе поверхности разойдутся."""
    _totals, reader = rendered()
    text = text_of(reader)
    assert "477000,00" in text
    assert "477000.00" not in text


# --- Кириллица и единицы ---


def test_cyrillic_survives_the_round_trip():
    _totals, reader = rendered()
    text = text_of(reader)
    for word in ("Смета", "Побелка потолка", "Цемент М500", "Наименование", "Итого"):
        assert word in text, word
    assert "?" not in text.replace("№", "")


def test_the_unit_is_printed_in_its_dictionary_form():
    """«мешков» сказано, «мешок» напечатано — падеж, а не другая единица."""
    _totals, reader = rendered()
    text = text_of(reader)
    assert "мешок" in text
    assert "мешков" not in text
    assert "м²" in text


def test_the_header_names_the_version_and_the_date():
    _totals, reader = rendered()
    text = text_of(reader)
    assert "Смета № 3, ред. 2" in text
    assert "3 августа 2026" in text
    assert "Отправлена заказчику" in text


# --- Что в файл не попадает ---


def test_the_document_carries_nothing_about_its_owner():
    """Файл уходит заказчику: ни id, ни имени владельца в нём быть не может."""
    _totals, reader = rendered()
    info = {key: str(value) for key, value in (reader.metadata or {}).items()}
    haystack = " ".join([*info.values(), text_of(reader)])

    assert "527183940" not in haystack
    assert not info.get("/Author"), "поле автора должно остаться пустым"


def test_an_empty_section_is_not_printed():
    only_work = [PositionData(Category.WORK, "Побелка", D("1"), D("100"))]
    _totals, reader = rendered(only_work)
    text = text_of(reader)
    assert "Работы" in text
    assert "Материалы" not in text


def test_a_long_estimate_repeats_the_header_on_every_page():
    many = [
        PositionData(Category.WORK, f"Работа {index}", D("1"), D("100"))
        for index in range(80)
    ]
    _totals, reader = rendered(many)
    assert len(reader.pages) > 1
    assert "Наименование" in reader.pages[1].extract_text()


# --- Шрифт ---


def test_the_font_travels_inside_the_repository():
    assert FONT_PATH.exists(), "шрифт должен лежать в репозитории, а не в системе"
    assert FONT_PATH.stat().st_size < 80_000, "урезанный шрифт не должен разрастаться"
    assert (FONT_PATH.parent / "OFL.txt").exists(), "лицензия лежит рядом со шрифтом"


def test_a_character_the_font_lacks_never_becomes_a_silent_box():
    """Найдено рендером страницы: «·» печатался пустым квадратом (ADR-021).

    Извлечение текста этого не видит — текстовый слой цел, сломана отрисовка.
    Поэтому символ вне шрифта заменяется знаком вопроса: он честнее квадрата
    и заметен тому, кто откроет документ.
    """
    assert printable("Побелка 🙂 потолка") == "Побелка ? потолка"
    assert printable("Смета · ред. 2 — «под ключ», 40,5 м² × 700 ₽") == (
        "Смета · ред. 2 — «под ключ», 40,5 м² × 700 ₽"
    )


def test_a_name_with_an_unrenderable_character_still_produces_a_document():
    """Эмодзи в наименовании не повод не выдать смету заказчику."""
    odd = [PositionData(Category.WORK, "Побелка 🙂 потолка", D("1"), D("100"))]
    _totals, reader = rendered(odd)
    assert "Побелка ? потолка" in text_of(reader)


def test_the_font_is_embedded_in_the_document():
    """Иначе у заказчика без этого шрифта кириллица развалится."""
    _totals, reader = rendered()
    fonts = reader.pages[0]["/Resources"]["/Font"]
    embedded = [str(fonts[key]["/BaseFont"]) for key in fonts]
    assert any("ProrabSans" in name for name in embedded), embedded


def test_the_modified_font_does_not_carry_the_reserved_name():
    """OFL: «PT Sans» и «ParaType» — зарезервированные имена (ADR-021)."""
    from fontTools.ttLib import TTFont

    names = {record.nameID: record.toUnicode() for record in TTFont(FONT_PATH)["name"].names}
    assert names[1] == "ProrabSans"
    assert not any(
        "PT Sans" in value or "ParaType" in value
        for nid, value in names.items() if nid != 0
    )
    assert "ParaType" in names[0], "копирайт обязан остаться (OFL)"


@pytest.mark.parametrize("symbol", ["₽", "×", "м²", "ё", "Ё", "—"])
def test_the_subset_keeps_what_an_estimate_actually_prints(symbol):
    from fontTools.ttLib import TTFont

    cmap = TTFont(FONT_PATH).getBestCmap()
    assert all(ord(char) in cmap for char in symbol), symbol


# --- Команда бота ---


@async_test
async def test_the_pdf_command_sends_a_document_with_the_domain_numbers(tmp_path, monkeypatch):
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'pdf.db'}"
    _engine, Session = open_storage(tmp_path / "pdf.db")

    from bot.handlers import files

    monkeypatch.setattr(files, "SessionLocal", Session)
    with Session() as db:
        estimate = create_estimate(db, UID, name="Ремонт")
        set_current_estimate(db, UID, estimate.id)
        for item in rows():
            positions.add(db, UID, estimate.id, item)
        db.commit()
        totals = calculate_estimate(rows(), D("6.00"), D("6.00"))

    message = FakeDocumentMessage()
    await files.cmd_pdf(FakeUpdate(message), None)

    [document] = message.documents
    assert document.filename.startswith("smeta_no1_v1_")
    assert document.filename.endswith(".pdf")
    assert str(UID) not in document.filename
    assert format_money(totals.total) in " ".join(message.sent)


@async_test
async def test_the_pdf_command_refuses_when_the_estimate_is_empty(tmp_path, monkeypatch):
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'empty.db'}"
    _engine, Session = open_storage(tmp_path / "empty.db")

    from bot.handlers import files

    monkeypatch.setattr(files, "SessionLocal", Session)
    with Session() as db:
        estimate = create_estimate(db, UID, name="Пустая")
        set_current_estimate(db, UID, estimate.id)

    message = FakeDocumentMessage()
    await files.cmd_pdf(FakeUpdate(message), None)
    assert not message.documents
    assert "Нет данных" in message.sent[0]


@async_test
async def test_a_document_is_not_issued_when_the_snapshot_disagrees(tmp_path, monkeypatch):
    """Данные разошлись с замороженным — файла не будет вовсе (money.md И3).

    Отказ здесь не перехватывается на месте: с Sprint 7 его объясняет один
    обработчик на всё приложение, одинаково для /list, /rate и документов.
    Поэтому тест проверяет две вещи по отдельности — что файл не ушёл и что
    человеку сказали, что произошло.
    """
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'broken.db'}"
    _engine, Session = open_storage(tmp_path / "broken.db")

    from bot.handlers import errors, files

    monkeypatch.setattr(files, "SessionLocal", Session)
    with Session() as db:
        estimate = create_estimate(db, UID, name="Ремонт")
        set_current_estimate(db, UID, estimate.id)
        for item in rows():
            positions.add(db, UID, estimate.id, item)
        db.commit()
        send(db, estimate)
        db.execute(text("UPDATE positions SET price_kop = 1 WHERE estimate_id = :i"),
                   {"i": estimate.id})
        db.commit()

    message = FakeDocumentMessage()
    with pytest.raises(IntegrityError) as caught:
        await files.cmd_pdf(FakeUpdate(message), None)
    assert not message.documents, "файл не должен уйти заказчику"

    await errors.on_error(ErrorUpdate(message), ErrorContext(caught.value))
    assert "разошлись" in message.sent[0]
    assert "/revise" in message.sent[0]

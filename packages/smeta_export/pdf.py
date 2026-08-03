"""PDF по смете. Числа приходят готовыми — считать здесь нечего.

В отличие от XLSX, где живут формулы, PDF содержит готовые числа. Поэтому он
их не вычисляет: `EstimateTotals` передаётся снаружи, и у отправленной сметы
это результат сверки со слепком (money.md И3). Второго вычислителя не
появляется — появляется второй потребитель.

Шрифт лежит в репозитории и встроен в файл: документ должен выглядеть
одинаково у прораба, у заказчика и в CI, где системных кириллических шрифтов
нет вовсе. Одно начертание — заголовки различаются кеглем и разрядкой.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from smeta_core import Category, EstimateTotals, format_money, format_qty, sum_lines
from smeta_prices import display_unit

FONT_NAME = "ProrabSans"
FONT_PATH = Path(__file__).parent / "fonts" / "ProrabSans-Regular.ttf"

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")

COLUMN_WIDTHS = (12 * mm, 74 * mm, 16 * mm, 20 * mm, 24 * mm, 26 * mm)
HEADERS = ("№", "Наименование", "Ед.", "Кол-во", "Цена", "Сумма")

GRID = colors.HexColor("#BFBFBF")
HEADER_BG = colors.HexColor("#EFEFEF")


@dataclass(frozen=True)
class DocumentMeta:
    """Шапка документа. Ничего о владельце здесь нет и быть не может."""

    number: int
    version: int
    title: str
    on: date
    work_rate: Decimal
    material_rate: Decimal
    status: str = ""


def _register_font() -> None:
    """Регистрация ленивая: импорт модуля не должен трогать файловую систему."""
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))


def printable(text: str) -> str:
    """Символы, которых нет в шрифте, заменяет на «?».

    Иначе они превращаются в пустой квадрат — и, что хуже, молча: извлечение
    текста из PDF показывает исходную строку, потому что текстовый слой цел, а
    сломана только отрисовка. Именно так в шапке документа жил квадрат вместо
    «·», и нашёлся он рендером страницы, а не тестом на текст.

    Наименование пишет человек; эмодзи или иероглиф в нём — редкость, но
    документ уходит заказчику, и знак вопроса там честнее квадрата.
    """
    _register_font()
    charset = pdfmetrics.getFont(FONT_NAME).face.charToGlyph
    return "".join(char if ord(char) in charset else "?" for char in text)


def _style(name: str, size: float, **kwargs) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=FONT_NAME, fontSize=size,
                          leading=size + 3, **kwargs)


def spell_date(on: date) -> str:
    return f"{on.day} {MONTHS[on.month - 1]} {on.year}"


def _table_style(rows: int) -> TableStyle:
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if rows:
        # Итоговая строка секции: без сетки слева, с разрядкой — жирного
        # начертания у нас нет намеренно (одно начертание в репозитории).
        commands += [
            ("SPAN", (0, -1), (4, -1)),
            ("ALIGN", (0, -1), (4, -1), "RIGHT"),
            ("BACKGROUND", (0, -1), (-1, -1), HEADER_BG),
        ]
    return TableStyle(commands)


def _rows(lines) -> list[list[str]]:
    body = []
    for index, line in enumerate(lines, start=1):
        position = line.position
        body.append([
            str(index),
            printable(position.name),
            printable(display_unit(position.unit, position.unit_spoken)) or "—",
            format_qty(position.qty),
            format_money(position.price),
            format_money(line.total),
        ])
    return body


def _section(title: str, lines, rate: Decimal, styles: dict) -> list:
    """Одна таблица: работы или материалы. Пустая секция не печатается."""
    if not lines:
        return []
    body = [list(HEADERS), *_rows(lines)]
    body.append(["", "", "", "", "", format_money(sum_lines(lines))])
    body[-1][0] = f"Итого, {title.lower()} (наценка {format_money(rate)}%)"

    table = Table(body, colWidths=COLUMN_WIDTHS, repeatRows=1, hAlign="LEFT")
    table.setStyle(_table_style(len(lines)))
    return [Paragraph(title, styles["section"]), Spacer(1, 2 * mm), table, Spacer(1, 6 * mm)]


def build_pdf(totals: EstimateTotals, meta: DocumentMeta) -> io.BytesIO:
    """Готовый документ. Суммы берутся из totals и не пересчитываются."""
    _register_font()
    styles = {
        "title": _style("title", 16),
        "meta": _style("meta", 9.5, textColor=colors.HexColor("#555555")),
        "section": _style("section", 11.5),
        "total": _style("total", 13, alignment=TA_RIGHT),
        "note": _style("note", 8, textColor=colors.HexColor("#777777")),
    }

    works = [line for line in totals.lines if line.position.category == Category.WORK]
    materials = [line for line in totals.lines if line.position.category == Category.MATERIAL]

    story: list = [
        Paragraph(f"Смета № {meta.number}, ред. {meta.version}", styles["title"]),
        Spacer(1, 2 * mm),
        Paragraph(printable(meta.title), styles["meta"]),
        Paragraph(
            " · ".join(part for part in (spell_date(meta.on), meta.status) if part),
            styles["meta"],
        ),
        Spacer(1, 7 * mm),
    ]
    story += _section("Работы", works, meta.work_rate, styles)
    story += _section("Материалы", materials, meta.material_rate, styles)
    story += [
        KeepTogether([
            Paragraph(f"Итого: {format_money(totals.total)} ₽", styles["total"]),
            Spacer(1, 1 * mm),
            Paragraph(
                f"в том числе наценка {format_money(totals.markup)} ₽ "
                f"(без наценки {format_money(totals.subtotal)} ₽)",
                styles["note"],
            ),
        ])
    ]

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Смета № {meta.number}, ред. {meta.version}",
        author="",       # автор пуст намеренно: документ уходит заказчику
        creator="Прораб",
        subject="",
    )
    document.build(story)
    buffer.seek(0)
    return buffer

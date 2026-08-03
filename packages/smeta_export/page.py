"""Публичная страница сметы: HTML, который открывается по ссылке без входа.

Ничего внешнего: ни шрифтов, ни картинок, ни скриптов, ни счётчиков. Причина
не в аккуратности вёрстки, а в том, что адрес страницы **и есть** секрет:
любой запрос к чужому домену унёс бы его в заголовке Referer — сначала к CDN
со шрифтом, потом в чужие логи, и ссылка на смету перестала бы быть частной.
Поэтому стили встроены, а шрифт берётся системный: у заказчика он уже есть,
и кириллица в браузере не требует ничего доставлять.

Это же отличает страницу от PDF. Там шрифт свой, урезанный, и символ вне
набора заменяется на «?» (ADR-021). Здесь набор — системный, полный, и имя
позиции показывается как есть.

Считать здесь нечего: EstimateTotals приходит готовым, как и в PDF.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape

from smeta_core import Category, EstimateTotals, format_money, format_qty, sum_lines
from smeta_prices import display_unit

from .document import DocumentMeta, document_subtitle, document_title, spell_date

# Системный стек. Ни одного @font-face: см. модульную строку выше.
FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", '
    "Arial, sans-serif"
)

# Стили уезжают заказчику целиком, поэтому объяснения живут здесь, а не внутри
# строки: комментарий в CSS — это вес в каждой выдаче и русский текст в чужом
# «просмотре кода страницы».
#
# table-layout: fixed и проценты по колонкам — не украшение. Без них браузер
# подбирает ширины по содержимому, и таблицы «Работы» и «Материалы» разъезжаются
# друг относительно друга. В PDF ширины заданы жёстко (COLUMN_WIDTHS); документ
# должен быть один, а не два похожих.
STYLE = f"""
* {{ box-sizing: border-box; }}
body {{
  font-family: {FONT_STACK};
  color: #1a1a1a; background: #fafafa;
  margin: 0; padding: 24px 16px 64px;
  font-size: 15px; line-height: 1.5;
}}
main {{ max-width: 860px; margin: 0 auto; background: #fff;
  border: 1px solid #e2e2e2; border-radius: 8px; padding: 28px 24px; }}
h1 {{ font-size: 22px; margin: 0 0 6px; font-weight: 600; }}
h2 {{ font-size: 16px; margin: 28px 0 8px; font-weight: 600; }}
.subtitle, .caption {{ color: #666; margin: 0 0 2px; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; min-width: 520px;
  table-layout: fixed; font-size: 14px; }}
th, td {{ border: 1px solid #d8d8d8; padding: 6px 8px; text-align: right; }}
th {{ background: #efefef; font-weight: 600; text-align: right; }}
th.name, td.name {{ text-align: left; overflow-wrap: break-word; }}
th.num, td.num {{ text-align: center; }}
th:nth-child(1) {{ width: 7%; }}
th:nth-child(2) {{ width: 37%; }}
th:nth-child(3) {{ width: 11%; }}
th:nth-child(4) {{ width: 13%; }}
th:nth-child(5) {{ width: 15%; }}
th:nth-child(6) {{ width: 17%; }}
tr.sum td {{ background: #efefef; }}
td.sum {{ text-align: right; }}
.total {{ margin-top: 28px; text-align: right; font-size: 20px; }}
.note {{ color: #777; font-size: 13px; text-align: right; margin: 4px 0 0; }}
.approval {{ margin-top: 32px; border-top: 1px solid #e2e2e2; padding-top: 20px; }}
.approved {{ color: #1d6f37; font-weight: 600; margin: 0; }}
button {{
  font: inherit; font-weight: 600; color: #fff; background: #1d6f37;
  border: 0; border-radius: 6px; padding: 12px 22px; cursor: pointer;
}}
.unavailable {{ max-width: 480px; margin: 15vh auto; text-align: center; color: #444; }}
"""

HEADERS = ("№", "Наименование", "Ед.", "Кол-во", "Цена", "Сумма")

# Выравнивание задаётся классом: номер по центру, наименование по левому краю,
# числа по правому — как в PDF и в XLSX.
COLUMN_CLASS = ("num", "name", "", "", "", "")

HEAD = "".join(
    f'<th class="{css}">{header}</th>' if css else f"<th>{header}</th>"
    for header, css in zip(HEADERS, COLUMN_CLASS, strict=True)
)

GONE_TITLE = "Ссылка недоступна"
GONE_TEXT = "Запросите новую у отправителя."


def _document(title: str, body: str) -> str:
    """Каркас. Внешних ресурсов здесь нет ни одного — это проверяется тестом."""
    return (
        "<!doctype html>\n"
        '<html lang="ru">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f"<title>{escape(title)}</title>\n"
        f"<style>{STYLE}</style>\n"
        f"</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def _row(index: int, line) -> str:
    position = line.position
    unit = escape(display_unit(position.unit, position.unit_spoken)) or "—"
    return (
        "<tr>"
        f'<td class="num">{index}</td>'
        f'<td class="name">{escape(position.name)}</td>'
        f"<td>{unit}</td>"
        f"<td>{format_qty(position.qty)}</td>"
        f"<td>{format_money(position.price)}</td>"
        f"<td>{format_money(line.total)}</td>"
        "</tr>"
    )


def _section(title: str, lines, rate: Decimal) -> str:
    """Одна таблица: работы или материалы. Пустая секция не печатается."""
    if not lines:
        return ""
    body = "".join(_row(index, line) for index, line in enumerate(lines, start=1))
    caption = f"Итого, {title.lower()} (наценка {format_money(rate)}%)"
    return (
        f"<h2>{escape(title)}</h2>\n"
        '<div class="scroll"><table>\n'
        f"<thead><tr>{HEAD}</tr></thead>\n"
        f"<tbody>{body}\n"
        f'<tr class="sum"><td class="sum" colspan="5">{escape(caption)}</td>'
        f'<td class="sum">{format_money(sum_lines(lines))}</td></tr>'
        "</tbody>\n</table></div>\n"
    )


def _approval(approve_url: str | None, approved_on: date | None) -> str:
    if approved_on is not None:
        return (
            '<div class="approval"><p class="approved">'
            f"✓ Согласовано {escape(spell_date(approved_on))}</p></div>"
        )
    if approve_url is None:
        return ""
    return (
        '<div class="approval">\n'
        f'<form method="post" action="{escape(approve_url, quote=True)}">\n'
        '<button type="submit">Согласовать смету</button>\n'
        "</form>\n</div>"
    )


def build_page(
    totals: EstimateTotals,
    meta: DocumentMeta,
    *,
    approve_url: str | None = None,
    approved_on: date | None = None,
) -> str:
    """Страница сметы. Суммы берутся из totals и не пересчитываются."""
    works = [line for line in totals.lines if line.position.category == Category.WORK]
    materials = [line for line in totals.lines if line.position.category == Category.MATERIAL]

    body = (
        "<main>\n"
        f"<h1>{escape(document_title(meta))}</h1>\n"
        f'<p class="subtitle">{escape(meta.title)}</p>\n'
        f'<p class="caption">{escape(document_subtitle(meta))}</p>\n'
        + _section("Работы", works, meta.work_rate)
        + _section("Материалы", materials, meta.material_rate)
        + f'<p class="total">Итого: {format_money(totals.total)} ₽</p>\n'
        + f'<p class="note">в том числе наценка {format_money(totals.markup)} ₽ '
        + f"(без наценки {format_money(totals.subtotal)} ₽)</p>\n"
        + _approval(approve_url, approved_on)
        + "\n</main>"
    )
    return _document(document_title(meta), body)


def unavailable_page() -> str:
    """Один ответ на все случаи: нет, отозвано, истекло, не сошлось.

    Причина не называется намеренно. Разный текст (или разный код ответа) на
    «такой ссылки не было» и «ссылку отозвали» — это оракул для перебора:
    он отвечает, существовал ли токен. Поэтому страница одна и говорит
    человеку то единственное, что ему полезно (ADR-020).
    """
    return _document(
        GONE_TITLE,
        f'<div class="unavailable"><h1>{GONE_TITLE}</h1><p>{GONE_TEXT}</p></div>',
    )

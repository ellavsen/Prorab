"""smeta-export — документы по смете. Считать здесь нечего, суммы приходят готовыми.

Три генератора, три разных набора зависимостей: XLSX нужен openpyxl, PDF —
reportlab, странице не нужно ничего. Поэтому **PDF импортируется лениво**:
браузерное демо на Pyodide ставит колёса руками, PDF там не делается вовсе, и
пакет обязан подниматься без reportlab. Проверяется тестом в отдельном
процессе, а не обещанием.
"""

from .document import DocumentMeta, document_subtitle, document_title, spell_date
from .naming import document_filename
from .page import build_page, unavailable_page
from .xlsx import FIRST_DATA_ROW, HEADER_ROW, RATE_CELL, build_sheet, build_workbook

__all__ = [
    "FIRST_DATA_ROW",
    "HEADER_ROW",
    "RATE_CELL",
    "DocumentMeta",
    "build_page",
    "build_pdf",
    "build_sheet",
    "build_workbook",
    "document_filename",
    "document_subtitle",
    "document_title",
    "spell_date",
    "unavailable_page",
]


def __getattr__(name: str):
    """`from smeta_export import build_pdf` работает, reportlab грузится тогда же."""
    if name == "build_pdf":
        from .pdf import build_pdf

        return build_pdf
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""smeta-ai — граница ввода: речь, фото и текст превращаются в кандидатов.

Слой отдаёт строки, а не деньги. Что из них станет позицией сметы, решает
домен: PositionData отвергает отрицательные количества, лишние знаки и выход
за границы. В смету кандидат попадает только после подтверждения человеком —
модель не пишет туда никогда (ADR-012).

Схема вложенная, потому что «цена не названа» и «цена ноль» — разные вещи, и
плоская строка их путает. Значения — строки: JSON-число это double.

Зависимость openai импортируется лениво, поэтому без ключа слой работает на
стандартной библиотеке.
"""

from .candidates import (
    TOTAL_UNIT,
    Confidence,
    Extraction,
    ExtractionStatus,
    FieldStatus,
    IgnoredFragment,
    PositionCandidate,
    Price,
    PriceScope,
    Quantity,
    pick_category,
    to_position,
)
from .collapse import collapse_total_scope, counted_name
from .openai_provider import DEFAULT_MODEL, OpenAIProvider, RefusedError
from .prompt import PROMPT_VERSION
from .protocols import AIProvider, Extractor, Transcriber
from .recorded import MissingRecording, RecordedProvider, recording_key
from .registry import build_provider
from .report import field_disagreements, format_report, report_to_dict, tag_rows
from .serialize import candidate_from_dict, extraction_from_dict, extraction_to_dict
from .stub import StubProvider
from .validate import check_candidate, quote_is_grounded, validate_extraction

__all__ = [
    "DEFAULT_MODEL",
    "PROMPT_VERSION",
    "TOTAL_UNIT",
    "AIProvider",
    "Confidence",
    "Extraction",
    "ExtractionStatus",
    "Extractor",
    "FieldStatus",
    "IgnoredFragment",
    "MissingRecording",
    "OpenAIProvider",
    "PositionCandidate",
    "Price",
    "PriceScope",
    "Quantity",
    "RecordedProvider",
    "RefusedError",
    "StubProvider",
    "Transcriber",
    "build_provider",
    "candidate_from_dict",
    "check_candidate",
    "collapse_total_scope",
    "counted_name",
    "extraction_from_dict",
    "extraction_to_dict",
    "field_disagreements",
    "format_report",
    "pick_category",
    "quote_is_grounded",
    "recording_key",
    "report_to_dict",
    "tag_rows",
    "to_position",
    "validate_extraction",
]

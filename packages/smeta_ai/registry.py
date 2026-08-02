"""Выбор провайдера. Без ключа — стаб, и это не аварийный режим, а норма.

Окружение здесь не читается: ключ передаёт вызывающий (у бота это config.py,
единственное место, где он смотрит в os.environ).
"""

from __future__ import annotations

from .openai_provider import DEFAULT_MODEL, OpenAIProvider
from .stub import StubProvider


def build_provider(api_key: str | None = None, model: str = DEFAULT_MODEL):
    """Живой провайдер, если есть ключ; иначе стаб (конституция, правило 7)."""
    if not api_key:
        return StubProvider()
    return OpenAIProvider(api_key=api_key, model=model)

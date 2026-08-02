"""Провайдер AI-слоя для процесса бота.

Без ключа поднимается стаб, и это происходит само: править конфиги, чтобы
запустить проект без ключей, не нужно (конституция, правило 7).
"""

from smeta_ai import build_provider

from .config import logger, openai_key

PROVIDER = build_provider(openai_key())
DEMO = PROVIDER.name == "stub"

logger.info("AI-слой: провайдер %s%s", PROVIDER.name, " (DEMO-режим)" if DEMO else "")

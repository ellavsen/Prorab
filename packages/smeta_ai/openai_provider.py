"""Провайдер OpenAI: Whisper для речи, gpt-4.1-mini для извлечения и фото.

Пакет openai импортируется лениво, внутри вызова. Без ключа этот модуль
никогда не доходит до импорта, поэтому DEMO-режим работает на голой
стандартной библиотеке (ADR-013).
"""

from __future__ import annotations

import base64
import json

from .candidates import Extraction
from .prompt import IMAGE_PROMPT, RESPONSE_SCHEMA, SYSTEM_PROMPT
from .serialize import extraction_from_dict

ASR_MODEL = "whisper-1"
DEFAULT_MODEL = "gpt-4.1-mini"

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "positions", "schema": RESPONSE_SCHEMA, "strict": True},
}


class RefusedError(RuntimeError):
    """Модель отказалась отвечать. Отказ — не пустой результат, и молчать о нём нельзя."""


def _parse(payload: str) -> Extraction:
    """Разбирает ответ модели. Схема строгая, но доверять ей на слово не будем."""
    return extraction_from_dict(json.loads(payload))


class OpenAIProvider:
    """Живой провайдер. Сеть только здесь."""

    name = "openai"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, asr_model: str = ASR_MODEL):
        self.model = model
        self.asr_model = asr_model
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # ленивый импорт: см. модульную docstring

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def transcribe(self, audio: bytes, filename: str) -> str:
        result = self._get_client().audio.transcriptions.create(
            model=self.asr_model, file=(filename, audio)
        )
        return (result.text or "").strip()

    def _complete(self, content) -> Extraction:
        response = self._get_client().chat.completions.create(
            model=self.model,
            response_format=_RESPONSE_FORMAT,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise RefusedError(message.refusal)
        return _parse(message.content or "{}")

    def extract(self, text: str) -> Extraction:
        return self._complete(text)

    def extract_from_image(self, image: bytes, media_type: str) -> Extraction:
        encoded = base64.b64encode(image).decode("ascii")
        return self._complete([
            {"type": "text", "text": IMAGE_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
        ])

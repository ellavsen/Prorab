"""Роли провайдера. Реализаций здесь нет — только форма.

Ролей две, потому что их закрывают разные модели: распознавание речи и
извлечение структуры. Один интерфейс на всё заставил бы стаб притворяться
сразу и ушами, и глазами (ADR-013).

Методы синхронные. Сетевой вызов в асинхронном хендлере телеграма блокирует
общий цикл, поэтому бот оборачивает их в asyncio.to_thread — зато слой
проверяется обычными тестами, без событийного цикла.
"""

from __future__ import annotations

from typing import Protocol

from .candidates import Extraction


class Transcriber(Protocol):
    """Речь -> текст."""

    def transcribe(self, audio: bytes, filename: str) -> str: ...


class Extractor(Protocol):
    """Текст или изображение -> разбор с кандидатами в позиции."""

    def extract(self, text: str) -> Extraction: ...

    def extract_from_image(self, image: bytes, media_type: str) -> Extraction: ...


class AIProvider(Transcriber, Extractor, Protocol):
    """Провайдер, закрывающий обе роли."""

    name: str

"""Записанные ответы модели: проигрывание в CI, запись по ключу.

Стаб в eval измеряет стаб. Живой вызов на каждом пуше недетерминирован и стоит
денег. Поэтому ответы модели записываются один раз и дальше проигрываются
(ADR-014).

Ключ записи включает версию промпта и модель: поменять промпт и не перезаписать
замер невозможно — фикстура просто не найдётся.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .candidates import Extraction
from .prompt import PROMPT_VERSION
from .serialize import extraction_from_dict, extraction_to_dict


class MissingRecording(RuntimeError):
    """Ответа на этот вход нет. Тихо подставить стаб нельзя — это подделка замера."""


def recording_key(kind: str, model: str, payload: bytes) -> str:
    digest = hashlib.sha256()
    for part in (kind, model, PROMPT_VERSION):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    digest.update(payload)
    return digest.hexdigest()[:32]


class RecordedProvider:
    """Проигрывает записанное. С inner — сначала записывает, чего не хватает."""

    name = "recorded"

    def __init__(self, directory: Path | str, model: str, inner=None):
        self.directory = Path(directory)
        self.model = model
        self.inner = inner

    def _path(self, kind: str, payload: bytes) -> Path:
        return self.directory / f"{recording_key(kind, self.model, payload)}.json"

    def _replay(self, kind: str, payload: bytes, preview: str, produce):
        path = self._path(kind, payload)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["result"]

        if self.inner is None:
            raise MissingRecording(
                f"нет записи {kind} для «{preview}» ({path.name}). "
                f"Записать: python scripts/run_eval.py --record"
            )

        result = produce()
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"kind": kind, "model": self.model, "prompt_version": PROMPT_VERSION,
                 "input": preview, "result": result},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        return result

    def transcribe(self, audio: bytes, filename: str) -> str:
        return self._replay(
            "transcribe", audio, filename, lambda: self.inner.transcribe(audio, filename)
        )

    def extract(self, text: str) -> Extraction:
        raw = self._replay(
            "extract", text.encode("utf-8"), text[:200],
            lambda: extraction_to_dict(self.inner.extract(text)),
        )
        return extraction_from_dict(raw)

    def extract_from_image(self, image: bytes, media_type: str) -> Extraction:
        raw = self._replay(
            "image", image, media_type,
            lambda: extraction_to_dict(self.inner.extract_from_image(image, media_type)),
        )
        return extraction_from_dict(raw)

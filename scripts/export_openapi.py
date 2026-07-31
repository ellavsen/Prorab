"""Выгружает OpenAPI-схему в docs/openapi.json.

Схема лежит в репозитории, чтобы изменение публичного интерфейса было видно
в диффе, а не обнаруживалось потребителем. CI сверяет её с кодом.
"""

import json
import pathlib
import sys

from api.main import app

TARGET = pathlib.Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    rendered = render()
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print("docs/openapi.json устарел. Обнови: python scripts/export_openapi.py")
            return 1
        print("docs/openapi.json совпадает с кодом")
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    print(f"записано: {TARGET.relative_to(TARGET.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

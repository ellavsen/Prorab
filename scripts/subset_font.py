#!/usr/bin/env python3
"""Готовит шрифт для PDF: скачивает, урезает набор символов, переименовывает.

Зачем скрипт, а не просто файл в репозитории: бинарник без происхождения
невозможно проверить. Здесь видно, что взято, откуда, что выброшено и почему
семейство называется иначе.

    python scripts/subset_font.py            # скачать и урезать
    python scripts/subset_font.py --check    # только показать размеры

Переименование обязательно. PT Sans распространяется под OFL 1.1 с
зарезервированным именем: модифицированную версию — а урезание это
модификация — под именем «PT Sans» распространять нельзя. Новое имя снимает
вопрос целиком и никого не вводит в заблуждение относительно происхождения:
оно в OFL.txt и в этом файле.
"""

from __future__ import annotations

import argparse
import io
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET_DIR = ROOT / "packages" / "smeta_export" / "fonts"
TARGET = TARGET_DIR / "ProrabSans-Regular.ttf"
LICENSE_TARGET = TARGET_DIR / "OFL.txt"

SOURCE = "https://github.com/google/fonts/raw/main/ofl/ptsans/PT_Sans-Web-Regular.ttf"
LICENSE_SOURCE = "https://github.com/google/fonts/raw/main/ofl/ptsans/OFL.txt"

FAMILY = "ProrabSans"

# Берём ВЕСЬ набор символов исходного шрифта, а не «то, что нужно смете».
# Закрытый список из 171 символа стоил бы 21 КБ вместо 58, но наименование
# позиции пишет человек, и любой символ вне списка стал бы в документе
# заказчика пустым квадратом — молча. Найдено рендером страницы: разделитель
# «·» в шапке был именно таким квадратом, а извлечение текста этого не видит.
#
# Ниже — то, что обязано быть в шрифте при любой пересборке. Это проверка
# покрытия, а не список для урезания.
REQUIRED = (
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    " .,:;!?()[]{}«»\"'—–-−+*/\\%№#@&_="
    "×÷²³°₽$€"
    "…·"
)  # ✓ и → в PT Sans отсутствуют вовсе — в документе их не используем


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def subset(raw: bytes) -> bytes:
    from fontTools import subset as fs
    from fontTools.ttLib import TTFont

    font = TTFont(io.BytesIO(raw))
    covered = list(font.getBestCmap())
    options = fs.Options()
    # Кернинг оставляем: он видно влияет на плотность строки. Лигатуры — нет:
    # в русской смете они не встречаются, а стоят 5 КБ.
    options.layout_features = ["kern"]
    # Хинтинг — 69 КБ из 90, три четверти файла. Это инструкции растеризации
    # для мелких кеглей на экранах низкой плотности; в печати они не работают
    # вовсе, а просмотрщики PDF растеризуют своими средствами. Обмен размера
    # на едва заметную мягкость на экране здесь очевиден.
    options.hinting = False
    # 0 — копирайт: OFL требует, чтобы он ехал с каждой копией. Пусть едет
    # и внутри файла, а не только в OFL.txt рядом.
    options.name_IDs = [0, 1, 2, 3, 4, 6]
    options.notdef_outline = True
    options.drop_tables += ["DSIG"]

    subsetter = fs.Subsetter(options=options)
    subsetter.populate(unicodes=covered)
    subsetter.subset(font)
    _rename(font)

    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _rename(font) -> None:
    """Меняет имя семейства: модифицированный OFL-шрифт не носит прежнее имя.

    Зарезервированы оба имени — и «PT Sans», и «ParaType», — поэтому
    идентификатор (nameID 3) переписывается целиком, а не заменой подстроки:
    иначе в нём осталось бы «ParaTypeLtd». Копирайт (nameID 0) остаётся как
    был: он не имя, а указание авторства, и его OFL требует сохранить.
    """
    for record in font["name"].names:
        if record.nameID == 3:
            value = f"{FAMILY}-Regular:2026"
        elif record.nameID in (1, 4, 6):
            value = record.toUnicode().replace("PT Sans", FAMILY).replace("PTSans", FAMILY)
        else:
            continue
        record.string = value.encode(record.getEncoding())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только показать размеры")
    args = parser.parse_args()

    from fontTools.ttLib import TTFont

    raw = fetch(SOURCE)
    trimmed = subset(raw)
    print(f"исходный:  {len(raw) / 1024:.1f} КБ")
    covered = len(TTFont(io.BytesIO(trimmed)).getBestCmap())
    missing = [c for c in REQUIRED if ord(c) not in TTFont(io.BytesIO(trimmed)).getBestCmap()]
    print(f"урезанный: {len(trimmed) / 1024:.1f} КБ  ({covered} символов)")
    if missing:
        raise SystemExit(f"в шрифте нет обязательных символов: {''.join(missing)}")
    if args.check:
        return 0

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(trimmed)
    LICENSE_TARGET.write_bytes(fetch(LICENSE_SOURCE))
    print(f"записано: {TARGET.relative_to(ROOT)}, {LICENSE_TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

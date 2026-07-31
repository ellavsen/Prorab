"""Готовит колёса для демо: то же ядро, что в боте и API, только для браузера.

Колёса не коммитятся — они собираются здесь и локально, и в CI, поэтому
демо считает ровно тем кодом, который лежит в packages/.
"""

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WHEELS = ROOT / "apps" / "web" / "public" / "wheels"

# Чистый Python, поэтому работают под Pyodide без компиляции.
RUNTIME_DEPS = ["openpyxl==3.1.5", "et_xmlfile==2.0.0"]


def run(*args: str) -> None:
    subprocess.run([sys.executable, "-m", *args], check=True, cwd=ROOT)


def main() -> int:
    if WHEELS.exists():
        shutil.rmtree(WHEELS)
    WHEELS.mkdir(parents=True)

    run("pip", "wheel", ".", "--no-deps", "-w", str(WHEELS), "-q")
    run("pip", "download", *RUNTIME_DEPS, "--no-deps", "--only-binary=:all:",
        "-d", str(WHEELS), "-q")

    names = sorted(p.name for p in WHEELS.glob("*.whl"))
    (WHEELS / "index.json").write_text(
        "[\n" + ",\n".join(f'  "{name}"' for name in names) + "\n]\n", encoding="utf-8"
    )
    for name in names:
        print("  ", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

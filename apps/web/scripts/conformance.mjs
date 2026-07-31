/**
 * Прогоняет векторы из tests/vectors/conformance.json в настоящем Pyodide.
 *
 * Смысл: доказать, что демо в браузере считает тем же кодом и с тем же
 * результатом, что CPython. Расхождение хоть на копейку — ненулевой код выхода.
 *
 * Запуск: npm run conformance (из apps/web)
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadPyodide } from "pyodide";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const ROOT = resolve(WEB, "..", "..");
const WHEELS = join(WEB, "public", "wheels");
const VECTORS = join(ROOT, "tests", "vectors", "conformance.json");

function fail(message) {
  console.error(`✗ ${message}`);
  process.exitCode = 1;
}

async function boot() {
  const pyodide = await loadPyodide();
  await pyodide.loadPackage("micropip");

  pyodide.FS.mkdir("/wheels");
  const wheels = readdirSync(WHEELS).filter((name) => name.endsWith(".whl"));
  for (const name of wheels) {
    pyodide.FS.writeFile(`/wheels/${name}`, readFileSync(join(WHEELS, name)));
  }

  const micropip = pyodide.pyimport("micropip");
  await micropip.install(wheels.map((name) => `emfs:/wheels/${name}`));

  pyodide.FS.mkdir("/app");
  pyodide.FS.writeFile(
    "/app/bridge.py",
    readFileSync(join(WEB, "public", "py", "bridge.py"), "utf-8"),
  );
  pyodide.runPython('import sys\nsys.path.insert(0, "/app")');

  const version = pyodide.runPython("import sys; sys.version.split()[0]");
  console.log(`Pyodide поднят, Python ${version}, колёс установлено: ${wheels.length}`);
  return pyodide.pyimport("bridge");
}

function compare(label, actual, expected) {
  const a = JSON.stringify(actual, Object.keys(actual).sort());
  const b = JSON.stringify(expected, Object.keys(expected).sort());
  if (a === b) return true;
  fail(`${label}\n  ожидалось: ${b.slice(0, 400)}\n  получено:  ${a.slice(0, 400)}`);
  return false;
}

const bridge = await boot();
const vectors = JSON.parse(readFileSync(VECTORS, "utf-8"));

let passed = 0;
for (const { name, request, expected } of vectors.calculate) {
  const actual = JSON.parse(bridge.calculate(JSON.stringify(request)));
  if (compare(`расчёт: ${name}`, actual, expected)) {
    console.log(`  ✓ ${name} — итого ${actual.total.text}`);
    passed += 1;
  }
}

for (const { request, expected } of vectors.parse) {
  const actual = JSON.parse(bridge.parse_lines(JSON.stringify(request)));
  if (compare(`разбор: ${request.text.split("\n")[0]}`, actual, expected)) {
    console.log(
      `  ✓ разбор ${request.category}: позиций ${actual.positions.length}, ошибок ${actual.errors.length}`,
    );
    passed += 1;
  }
}

// XLSX собирается в браузере тем же build_workbook — проверяем, что файл живой.
const xlsx = JSON.parse(bridge.xlsx_base64(JSON.stringify(vectors.calculate[0].request)));
if (xlsx.error) {
  fail(`xlsx: ${xlsx.error}`);
} else {
  const bytes = Buffer.from(xlsx.base64, "base64");
  const isZip = bytes[0] === 0x50 && bytes[1] === 0x4b;
  if (!isZip) fail("xlsx: получен не zip-контейнер");
  else {
    console.log(`  ✓ xlsx собран в браузерном ядре, ${bytes.length} байт`);
    passed += 1;
  }
}

const total = vectors.calculate.length + vectors.parse.length + 1;
console.log(
  process.exitCode ? `\n${passed}/${total} — есть расхождения` : `\n${passed}/${total} совпало`,
);

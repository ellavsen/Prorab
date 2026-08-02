/**
 * Мост к ядру. Всё, что связано с деньгами, считает Python внутри Pyodide —
 * тот же smeta_core, что работает в боте и в API. Здесь нет ни одной
 * арифметической операции над суммами, и появиться она не должна.
 */

export type Money = { value: string; text: string };

export type Position = {
  category: "work" | "material";
  name: string;
  unit: string;
  qty: string;
  qty_text: string;
  price: string;
  price_text: string;
};

export type Line = Position & { base: Money; total: Money };

export type Totals = {
  lines: Line[];
  subtotal: Money;
  markup: Money;
  total: Money;
};

export type ParseResult = {
  positions: Position[];
  errors: { line: string; reason: string }[];
};

export type Estimate = {
  positions: Position[];
  markup_work_rate: string;
  markup_material_rate: string;
};

type Bridge = {
  parse_lines: (payload: string) => string;
  calculate: (payload: string) => string;
  xlsx_base64: (payload: string) => string;
};

declare global {
  interface Window {
    loadPyodide: (options: { indexURL: string }) => Promise<PyodideRuntime>;
  }
}

type PyodideRuntime = {
  loadPackage: (name: string) => Promise<void>;
  pyimport: (name: string) => Bridge & { install: (urls: string[]) => Promise<void> };
  runPython: (code: string) => unknown;
  FS: { mkdir: (path: string) => void; writeFile: (path: string, data: string) => void };
};

const PYODIDE_INDEX = "https://cdn.jsdelivr.net/pyodide/v314.0.3/full/";

function asset(path: string): string {
  return `${import.meta.env.BASE_URL}${path}`.replace(/\/{2,}/g, "/");
}

let booting: Promise<Bridge> | null = null;

async function boot(report: (stage: string) => void): Promise<Bridge> {
  report("Загружаю Python…");
  const pyodide = await window.loadPyodide({ indexURL: PYODIDE_INDEX });

  report("Ставлю ядро…");
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  const wheels: string[] = await fetch(asset("wheels/index.json")).then((r) => r.json());
  await micropip.install(wheels.map((name) => asset(`wheels/${name}`)));

  report("Готовлю расчёт…");
  const source = await fetch(asset("py/bridge.py")).then((r) => r.text());
  pyodide.FS.mkdir("/app");
  pyodide.FS.writeFile("/app/bridge.py", source);
  pyodide.runPython('import sys\nsys.path.insert(0, "/app")');
  return pyodide.pyimport("bridge") as Bridge;
}

/** Ядро поднимается один раз на страницу. */
export function loadCore(report: (stage: string) => void): Promise<Bridge> {
  if (booting === null) booting = boot(report);
  return booting;
}

export async function parseLines(
  bridge: Bridge,
  category: Position["category"],
  text: string,
): Promise<ParseResult> {
  return JSON.parse(bridge.parse_lines(JSON.stringify({ category, text })));
}

export async function calculate(bridge: Bridge, estimate: Estimate): Promise<Totals> {
  const result = JSON.parse(bridge.calculate(JSON.stringify(estimate)));
  if (result.error) throw new Error(result.error);
  return result as Totals;
}

export async function downloadXlsx(bridge: Bridge, estimate: Estimate): Promise<void> {
  const result = JSON.parse(bridge.xlsx_base64(JSON.stringify(estimate)));
  if (result.error) throw new Error(result.error);

  const bytes = Uint8Array.from(atob(result.base64), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "smeta.xlsx";
  link.click();
  URL.revokeObjectURL(url);
}

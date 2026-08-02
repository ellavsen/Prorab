import { useCallback, useEffect, useState } from "react";

import {
  calculate,
  downloadXlsx,
  loadCore,
  parseLines,
  type Estimate,
  type Position,
  type Totals,
} from "./core";

type Category = Position["category"];
type Bridge = Awaited<ReturnType<typeof loadCore>>;

// Категории в коде английские, на экране русские: подпись — дело адаптера.
const LABEL: Record<Category, string> = { work: "Работа", material: "Материал" };

const PLACEHOLDER: Record<Category, string> = {
  work: "Побелка, 150 м2, 3000\nСтяжка, 40.5 м2, 1200",
  material: "Гвозди, 1000 шт, 20\nЦемент, 12 меш, 450",
};

export default function App() {
  const [bridge, setBridge] = useState<Bridge | null>(null);
  const [stage, setStage] = useState("Запускаю…");
  const [failed, setFailed] = useState<string | null>(null);

  const [category, setCategory] = useState<Category>("work");
  const [draft, setDraft] = useState(PLACEHOLDER["work"]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [workRate, setWorkRate] = useState("6.00");
  const [materialRate, setMaterialRate] = useState("6.00");

  const [totals, setTotals] = useState<Totals | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  useEffect(() => {
    loadCore(setStage).then(setBridge).catch((e) => setFailed(String(e)));
  }, []);

  const estimate: Estimate = {
    positions,
    markup_work_rate: workRate,
    markup_material_rate: materialRate,
  };

  const recalculate = useCallback(
    async (next: Position[]) => {
      if (!bridge) return;
      if (next.length === 0) {
        setTotals(null);
        return;
      }
      try {
        setTotals(
          await calculate(bridge, {
            positions: next,
            markup_work_rate: workRate,
            markup_material_rate: materialRate,
          }),
        );
        setProblems([]);
      } catch (error) {
        setTotals(null);
        setProblems([String(error instanceof Error ? error.message : error)]);
      }
    },
    [bridge, workRate, materialRate],
  );

  useEffect(() => {
    void recalculate(positions);
  }, [recalculate, positions]);

  async function addLines() {
    if (!bridge) return;
    const parsed = await parseLines(bridge, category, draft);
    setProblems(parsed.errors.map((e) => `«${e.line}» — ${e.reason.split("\n")[0]}`));
    if (parsed.positions.length > 0) {
      setPositions([...positions, ...parsed.positions]);
      setDraft("");
    }
  }

  function switchCategory(next: Category) {
    setCategory(next);
    if (draft.trim() === "" || draft === PLACEHOLDER[category]) setDraft(PLACEHOLDER[next]);
  }

  if (failed !== null) {
    return (
      <main className="wrap">
        <h1>Прораб</h1>
        <p className="error">Не удалось запустить ядро: {failed}</p>
      </main>
    );
  }

  return (
    <main className="wrap">
      <header>
        <h1>Прораб</h1>
        <p className="lead">
          Смета считается <b>прямо в браузере</b>: Python-ядро проекта собрано в WebAssembly.
          Бэкенда нет — закройте вкладку, и ничего никуда не ушло.
        </p>
      </header>

      {bridge === null ? (
        <p className="loading">{stage} Первый запуск занимает несколько секунд.</p>
      ) : (
        <>
          <section className="card">
            <div className="tabs">
              {(["work", "material"] as Category[]).map((value) => (
                <button
                  key={value}
                  className={value === category ? "tab active" : "tab"}
                  onClick={() => switchCategory(value)}
                >
                  {LABEL[value]}
                </button>
              ))}
            </div>
            <textarea
              value={draft}
              rows={4}
              spellCheck={false}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={PLACEHOLDER[category]}
            />
            <div className="row">
              <button className="primary" onClick={addLines}>
                Добавить
              </button>
              <span className="hint">
                Наименование, количество, цена — по одной позиции в строке
              </span>
            </div>
          </section>

          {problems.length > 0 && (
            <ul className="problems">
              {problems.map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
          )}

          <section className="card rates">
            <label>
              Наценка на работы, %
              <input value={workRate} onChange={(e) => setWorkRate(e.target.value)} />
            </label>
            <label>
              Наценка на материалы, %
              <input value={materialRate} onChange={(e) => setMaterialRate(e.target.value)} />
            </label>
          </section>

          {totals !== null && (
            <section className="card">
              <table>
                <thead>
                  <tr>
                    <th>Наименование</th>
                    <th>Кол-во</th>
                    <th>Цена</th>
                    <th>Сумма</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {totals.lines.map((line, index) => (
                    <tr key={index}>
                      <td>
                        {line.name}
                        <span className="tag">{LABEL[line.category]}</span>
                      </td>
                      <td className="num">
                        {line.qty_text} {line.unit}
                      </td>
                      <td className="num">{line.price_text}</td>
                      <td className="num">{line.total.text}</td>
                      <td>
                        <button
                          className="drop"
                          title="Удалить"
                          onClick={() =>
                            setPositions(positions.filter((_, i) => i !== index))
                          }
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3}>Без наценки</td>
                    <td className="num">{totals.subtotal.text}</td>
                    <td />
                  </tr>
                  <tr>
                    <td colSpan={3}>Наценка</td>
                    <td className="num">{totals.markup.text}</td>
                    <td />
                  </tr>
                  <tr className="grand">
                    <td colSpan={3}>Итого</td>
                    <td className="num">{totals.total.text}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
              <div className="row">
                <button
                  className="primary"
                  onClick={() =>
                    downloadXlsx(bridge, estimate).catch((e) => setProblems([String(e)]))
                  }
                >
                  Скачать XLSX
                </button>
                <span className="hint">
                  В файле живые формулы <code>=ROUND(...)</code> и та же сумма до копейки
                </span>
              </div>
            </section>
          )}

          <footer>
            Итог — сумма уже округлённых строк, поэтому сложенные глазами строки и «Итого»
            совпадают. Считает <code>calculate_estimate</code> из <code>smeta_core</code>,
            один и тот же код в боте, в API и здесь.
          </footer>
        </>
      )}
    </main>
  );
}

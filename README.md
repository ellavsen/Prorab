# Прораб — AI-сметчик в кармане

> Смета голосом. За 30 секунд. С объекта.

**LLM превращает речь, фото и текст в структуру. Деньги считает код.**

ИИ работает только на границе ввода и всегда через предпросмотр с подтверждением.
Ядро расчёта — детерминированное, на `Decimal`, покрытое тестами.

---

## Статус

🚧 Проект в пересборке по плану в [smeta_master_plan.md](python3/webservice/smeta_master_plan.md).

Работающий прототип: Telegram-бот на `python-telegram-bot` + SQLAlchemy + openpyxl,
собирает сметы по позициям и отдаёт XLSX с живыми формулами.

| Спринт | Что даёт | Статус |
|---|---|---|
| 0 | Гигиена и безопасность | готово |
| 1 | Финансовое ядро `smeta-core` + тесты | готово |
| 2 | Разбор монолита на пакеты | — |
| 3 | FastAPI + веб-демо на GitHub Pages | — |
| 5 | Голос → смета | — |
| 6 | `price-radar` — мониторинг цен | — |

## Как считаются деньги

Единственный источник истины — `calculate_estimate()` в [packages/smeta_core/](packages/smeta_core/).
Ни бот, ни Excel не считают сами: они показывают её результат.

```
factor   = 1 + ставка/100
base     = round2(количество × цена)      ROUND_HALF_UP
line     = round2(base × factor)
subtotal = Σ base,  total = Σ line,  наценка = total − subtotal
```

Итог — сумма **уже округлённых** строк, поэтому «сложить строки глазами» и
«посмотреть Итого» даёт одно и то же число. Формулы в XLSX — транскрипция той же
схемы (`=ROUND(C4*D4,2)`, `=ROUND(E4*(1+$B$1/100),2)`), а не второй расчёт.

Деньги — только `Decimal`; в SQLite хранятся целыми (`price_kop`, `qty_milli`),
потому что `NUMERIC` там физически REAL. Наценка живёт в самой смете, а не в
глобальной константе: смена ставки не переписывает уже выставленные сметы.

Подробности: [docs/money.md](docs/money.md), решения — [docs/decisions/](docs/decisions/).

## Запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r python3/webservice/requirements.txt
pip install -e .                              # ставит smeta-core
cp .env.example .env                          # вписать TELEGRAM_BOT_TOKEN от @BotFather
python python3/webservice/telegram/main_agent.py
```

## Тесты

```bash
pip install -r requirements-dev.txt
pytest --cov=smeta_core
```

121 тест, покрытие ядра 100%. Среди них — прогон на 10 000 случайных смет,
проверяющий, что Telegram, сводка и Excel дают одинаковый итог до копейки.
Тест `test_e1_libreoffice_recalculation_matches` пропускается, если LibreOffice
не установлен: без него пересчитать формулы нечем.

## Лицензия

MIT — см. [LICENSE](LICENSE).

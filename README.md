# Прораб — AI-сметчик в кармане

> Смета голосом. За 30 секунд. С объекта.

**LLM превращает речь, фото и текст в структуру. Деньги считает код.**

ИИ работает только на границе ввода и всегда через предпросмотр с подтверждением.
Ядро расчёта — детерминированное, на `Decimal`, покрытое тестами.

---

## Статус

🚧 Проект в пересборке. Сейчас идёт Sprint 0 (гигиена и безопасность) из
плана в [smeta_master_plan.md](python3/webservice/smeta_master_plan.md).

Работающий прототип: Telegram-бот на `python-telegram-bot` + SQLAlchemy + openpyxl,
собирает сметы по позициям и отдаёт XLSX с живыми формулами.

| Спринт | Что даёт | Статус |
|---|---|---|
| 0 | Гигиена и безопасность | в работе |
| 1 | Финансовое ядро `smeta-core` + тесты | — |
| 2 | Разбор монолита на пакеты | — |
| 3 | FastAPI + веб-демо на GitHub Pages | — |
| 5 | Голос → смета | — |
| 6 | `price-radar` — мониторинг цен | — |

## Запуск

```bash
pip install -r python3/webservice/requirements.txt
cp .env.example .env        # вписать TELEGRAM_BOT_TOKEN от @BotFather
python python3/webservice/telegram/main_agent.py
```

## Лицензия

MIT — см. [LICENSE](LICENSE).

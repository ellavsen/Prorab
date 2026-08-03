"""Подключение к базе. Схему создаёт бот — публичное приложение её не трогает.

bootstrap здесь не вызывается намеренно: сервис, отдающий данные наружу, не
должен иметь причин менять схему. Если таблицы ссылок ещё нет, значит бот на
этой базе не поднимался, и чинить это надо там.
"""

from smeta_storage import build_engine, build_sessionmaker

engine = build_engine()
SessionLocal = build_sessionmaker(engine)

"""Подключение к базе для процесса бота. Схема готова до первого хендлера."""

from smeta_storage import bootstrap, build_engine, build_sessionmaker

engine = build_engine()
SessionLocal = build_sessionmaker(engine)

bootstrap(engine)

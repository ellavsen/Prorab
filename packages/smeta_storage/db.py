"""Подключение к базе. Единственное место, где читается ESTIMATE_DB_URL."""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DB_URL = "sqlite:///estimate.db"


def build_engine(url: str | None = None) -> Engine:
    return create_engine(url or os.getenv("ESTIMATE_DB_URL", DEFAULT_DB_URL), future=True)


def build_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)

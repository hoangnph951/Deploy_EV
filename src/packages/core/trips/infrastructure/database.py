from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def normalize_database_url(database_url: str) -> str:
    is_postgresql = database_url.startswith(("postgresql://", "postgresql+psycopg2://"))
    hostname = urlsplit(database_url).hostname
    is_local = hostname in {"localhost", "127.0.0.1", "::1"}

    if is_postgresql and not is_local and "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        return f"{database_url}{separator}sslmode=require"
    return database_url


def build_engine(database_url: str):
    normalized_url = normalize_database_url(database_url)
    connect_args: dict[str, str] = {}

    if normalized_url.startswith("sqlite:///"):
        sqlite_path = normalized_url.replace("sqlite:///", "", 1)
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False

    return create_engine(normalized_url, future=True, pool_pre_ping=True, connect_args=connect_args)


def build_session_factory(database_url: str):
    engine = build_engine(database_url)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)

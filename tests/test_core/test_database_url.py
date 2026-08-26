from src.packages.core.trips.infrastructure.database import normalize_database_url


def test_local_postgres_does_not_force_ssl() -> None:
    url = "postgresql://postgres:postgres@localhost:5432/ai_ev"

    assert normalize_database_url(url) == url


def test_remote_postgres_requires_ssl_by_default() -> None:
    url = "postgresql://postgres:secret@example.supabase.com:5432/postgres"

    assert normalize_database_url(url) == f"{url}?sslmode=require"


def test_explicit_ssl_mode_is_preserved() -> None:
    url = "postgresql://postgres:postgres@localhost:5432/ai_ev?sslmode=disable"

    assert normalize_database_url(url) == url

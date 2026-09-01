from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from src.apps.api.bootstrap.config import get_settings
from src.packages.core.auth.infrastructure import models as auth_models  # noqa: F401
from src.packages.core.policies.infrastructure import models as policy_models  # noqa: F401
from src.packages.core.replanning.infrastructure import models as replanning_models  # noqa: F401
from src.packages.core.trips.infrastructure import models as trip_models  # noqa: F401
from src.packages.core.trips.infrastructure.database import Base, normalize_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    settings = get_settings()
    return normalize_database_url(settings.database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    from sqlalchemy import engine_from_config, pool

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

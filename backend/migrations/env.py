"""Alembic environment. Runs as the owner role via MIGRATIONS_DATABASE_URL."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
target_metadata = None  # models arrive with Phase 1


def _url() -> str:
    url = os.environ.get("MIGRATIONS_DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATIONS_DATABASE_URL is not set")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema="cbam",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.begin() as connection:
        # The version table lives in cbam, so the schema must exist before Alembic starts.
        connection.exec_driver_sql("create schema if not exists cbam")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="cbam",
        )
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

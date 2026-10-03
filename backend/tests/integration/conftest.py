"""Integration fixtures: a migrated throwaway database and an engine for role cbam_app.

Needs TEST_DATABASE_URL pointing at a database where the connecting user can create
roles (see test_migrations.py). Tests connect as `cbam_app`, the role the app uses, so
row-level security applies exactly as in production.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.core.db import make_engine, tenant_session
from app.core.ids import uuid7

TEST_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND = Path(__file__).resolve().parents[2]
APP_PASSWORD = "cbam_app_test_only"  # noqa: S105 - throwaway test database


def _migrate() -> None:
    assert TEST_URL
    previous = os.environ.get("MIGRATIONS_DATABASE_URL")
    os.environ["MIGRATIONS_DATABASE_URL"] = TEST_URL
    try:
        cfg = Config(str(BACKEND / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("MIGRATIONS_DATABASE_URL", None)
        else:
            os.environ["MIGRATIONS_DATABASE_URL"] = previous


@pytest.fixture
def admin_engine() -> Iterator[Engine]:
    """Owner/superuser connection: bypasses RLS, used only for setup and inspection."""
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    _migrate()
    engine = create_engine(TEST_URL)
    with engine.begin() as conn:
        conn.execute(text(f"alter role cbam_app login password '{APP_PASSWORD}'"))
    yield engine
    engine.dispose()


@pytest.fixture
def app_engine(admin_engine: Engine) -> Iterator[Engine]:
    assert TEST_URL
    url = make_url(TEST_URL).set(username="cbam_app", password=APP_PASSWORD)
    engine = make_engine(url.render_as_string(hide_password=False))
    yield engine
    engine.dispose()


def make_tenant(engine: Engine, name: str = "Test tenant") -> UUID:
    """Create a tenant through the real policy path: a verified platform admin."""
    tenant_id = uuid7()
    with tenant_session(engine, tenant_id=None, platform=True) as s:
        s.execute(
            text("insert into cbam.tenants (id, name) values (:id, :name)"),
            {"id": tenant_id, "name": name},
        )
    return tenant_id


def make_org(engine: Engine, tenant_id: UUID, legal_name: str) -> UUID:
    org_id = uuid7()
    with tenant_session(engine, tenant_id=tenant_id) as s:
        s.execute(
            text("insert into cbam.organisations (id, tenant_id, legal_name) values (:i, :t, :n)"),
            {"i": org_id, "t": tenant_id, "n": legal_name},
        )
    return org_id

"""Phase 0 step 7: migrations run up, down, up and lock the Supabase API roles out of cbam.

Needs a throwaway Postgres in TEST_DATABASE_URL (owner/superuser rights, because the first
migration creates roles). Skipped when the variable is not set.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

TEST_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set")

BACKEND = Path(__file__).resolve().parents[2]


def _config(monkeypatch: pytest.MonkeyPatch) -> Config:
    assert TEST_URL
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", TEST_URL)
    return Config(str(BACKEND / "alembic.ini"))


def _scalar(sql: str) -> object:
    assert TEST_URL
    with create_engine(TEST_URL).connect() as conn:
        return conn.execute(text(sql)).scalar()


def test_migrations_up_down_up(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _config(monkeypatch)
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    assert _scalar("select has_schema_privilege('cbam_app', 'cbam', 'usage')") is True
    command.downgrade(cfg, "base")
    assert _scalar("select has_schema_privilege('cbam_app', 'cbam', 'usage')") is False
    command.upgrade(cfg, "head")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert _scalar("select version_num from cbam.alembic_version") == head


def test_app_role_is_not_owner_and_cannot_bypass_rls(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE.md rule 7 / docs/DATABASE.md section 2: cbam_app is not owner, no BYPASSRLS."""
    command.upgrade(_config(monkeypatch), "head")
    assert (
        _scalar("select rolbypassrls or rolsuper from pg_roles where rolname = 'cbam_app'") is False
    )
    assert (
        _scalar("select pg_get_userbyid(nspowner) from pg_namespace where nspname = 'cbam'")
        == "cbam_owner"
    )


def test_supabase_api_roles_have_no_access_to_cbam(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE.md rule 18: anon/authenticated never reach the cbam schema."""
    command.upgrade(_config(monkeypatch), "head")
    for role in ("anon", "authenticated"):
        exists = _scalar(f"select count(*) from pg_roles where rolname = '{role}'")  # noqa: S608
        if exists:
            sql = f"select has_schema_privilege('{role}', 'cbam', 'usage')"
            assert _scalar(sql) is False

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


def test_0009_import_tables_are_removed_by_downgrade_and_come_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1-003: migration 0009 has a working downgrade (tables, trigger functions) and re-applies."""
    cfg = _config(monkeypatch)
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    count = (
        "select count(*) from information_schema.tables where table_schema = 'cbam' "
        "and table_name in ('documents','document_versions','import_batches')"
    )
    functions = (
        "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'cbam' and p.proname like any "
        "(array['import_batches_%', 'documents_block_change'])"
    )
    assert _scalar(count) == 3
    assert _scalar(functions) == 3
    command.downgrade(cfg, "0008")
    assert _scalar(count) == 0
    assert _scalar(functions) == 0
    command.upgrade(cfg, "head")
    assert _scalar(count) == 3


def test_0011_import_lines_and_the_impact_function_are_removed_by_downgrade_and_come_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1-005: migration 0011 has a working downgrade (tables, functions, lease_owner)."""
    cfg = _config(monkeypatch)
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")
    tables = (
        "select count(*) from information_schema.tables where table_schema = 'cbam' "
        "and table_name in ('parties','declarations','import_lines','import_line_sources')"
    )
    column = (
        "select count(*) from information_schema.columns where table_schema = 'cbam' "
        "and table_name = 'import_batches' and column_name = 'lease_owner'"
    )
    functions = (
        "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'cbam' and p.proname in ('impact_line_counts_by_code_prefix', "
        "'import_facts_block_change', 'declarations_check_chain', 'import_lines_check_chain')"
    )
    assert (_scalar(tables), _scalar(column), _scalar(functions)) == (4, 1, 4)
    command.downgrade(cfg, "0010")
    assert (_scalar(tables), _scalar(column), _scalar(functions)) == (0, 0, 0)
    assert _scalar("select count(*) from cbam.source_rows") is not None  # 0010 is intact
    command.upgrade(cfg, "head")
    assert (_scalar(tables), _scalar(column), _scalar(functions)) == (4, 1, 4)
    forced = (
        "select count(*) from pg_class where relnamespace = 'cbam'::regnamespace and relname in "
        "('parties','declarations','import_lines','import_line_sources') "
        "and relrowsecurity and relforcerowsecurity"
    )
    assert _scalar(forced) == 4


def test_0011_review_fixes_index_hash_version_and_the_impact_reader_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command.upgrade(_config(monkeypatch), "head")
    assert (
        _scalar(
            "select count(*) from pg_indexes where schemaname = 'cbam' "
            "and indexname = 'row_exceptions_source_row'"
        )
        == 1
    )
    assert (
        _scalar(
            "select count(*) from information_schema.columns where table_schema = 'cbam' "
            "and column_name = 'hash_version' and table_name in ('declarations','import_lines')"
        )
        == 2
    )
    # a NOLOGIN role that owns the function and can only read the lines
    assert (
        _scalar(
            "select rolcanlogin or rolsuper or rolbypassrls or rolcreaterole "
            "from pg_roles where rolname = 'cbam_impact_reader'"
        )
        is False
    )
    assert (
        _scalar(
            "select pg_get_userbyid(proowner) from pg_proc "
            "where proname = 'impact_line_counts_by_code_prefix'"
        )
        == "cbam_impact_reader"
    )

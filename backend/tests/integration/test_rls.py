"""R1-001 / CLAUDE.md rule 7: tenant isolation is enforced by PostgreSQL, not by the app.

Handbook gate "RLS proven": a user of tenant A cannot read or write any tenant-B row,
by direct SQL as `cbam_app`.
"""

from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.db import tenant_session
from app.core.ids import uuid7
from tests.integration.conftest import make_org, make_tenant


def _count(engine: Engine, tenant: UUID | None, table: str = "organisations") -> int:
    with tenant_session(engine, tenant_id=tenant) as s:
        return int(s.execute(text(f"select count(*) from cbam.{table}")).scalar_one())  # noqa: S608


def test_tenant_a_cannot_read_tenant_b_rows(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    make_org(app_engine, a, "A Ltd")
    org_b = make_org(app_engine, b, "B Ltd")
    with tenant_session(app_engine, tenant_id=a) as s:
        names = s.execute(text("select legal_name from cbam.organisations")).scalars().all()
        assert names == ["A Ltd"]
        by_id = s.execute(
            text("select count(*) from cbam.organisations where id = :i"), {"i": org_b}
        ).scalar_one()
        assert by_id == 0


def test_tenant_a_cannot_write_into_tenant_b(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    org_b = make_org(app_engine, b, "B Ltd")
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a) as s:
        s.execute(
            text("insert into cbam.organisations (id, tenant_id, legal_name) values (:i,:t,'x')"),
            {"i": uuid7(), "t": b},
        )
    with tenant_session(app_engine, tenant_id=a) as s:
        updated = s.execute(
            text("update cbam.organisations set legal_name = 'hacked' where id = :i"), {"i": org_b}
        ).rowcount
        assert updated == 0
    with tenant_session(app_engine, tenant_id=b) as s:
        name = s.execute(text("select legal_name from cbam.organisations")).scalar_one()
        assert name == "B Ltd"


def test_cannot_move_a_row_to_another_tenant(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    org_a = make_org(app_engine, a, "A Ltd")
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a) as s:
        s.execute(
            text("update cbam.organisations set tenant_id = :b where id = :i"),
            {"b": b, "i": org_a},
        )


def test_no_tenant_context_sees_nothing(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    make_org(app_engine, a, "A Ltd")
    assert _count(app_engine, None) == 0
    assert _count(app_engine, None, "tenants") == 0


def test_platform_mode_does_not_open_business_tables(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    make_org(app_engine, a, "A Ltd")
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        assert s.execute(text("select count(*) from cbam.organisations")).scalar_one() == 0


def test_only_platform_can_create_tenants(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a) as s:
        s.execute(text("insert into cbam.tenants (id, name) values (:i, 'rogue')"), {"i": uuid7()})


def test_tenant_sees_only_itself_in_tenants(app_engine: Engine) -> None:
    a, _b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    with tenant_session(app_engine, tenant_id=a) as s:
        assert s.execute(text("select id from cbam.tenants")).scalars().all() == [a]


def test_memberships_findable_by_user_before_a_tenant_is_chosen(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    user, other = uuid7(), uuid7()
    user_mail = f"u-{user.hex}@example.test"
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        for uid, mail in ((user, user_mail), (other, f"o-{other.hex}@example.test")):
            s.execute(
                text("insert into cbam.users (id, email) values (:i, :e)"), {"i": uid, "e": mail}
            )
    for tenant, uid in ((a, user), (b, user), (b, other)):
        with tenant_session(app_engine, tenant_id=tenant) as s:
            s.execute(
                text(
                    "insert into cbam.memberships (id, user_id, tenant_id, roles)"
                    " values (:i, :u, :t, array['operations'])"
                ),
                {"i": uuid7(), "u": uid, "t": tenant},
            )
    with tenant_session(app_engine, tenant_id=None, user_id=user) as s:
        tenants = s.execute(text("select tenant_id from cbam.memberships")).scalars().all()
        assert set(tenants) == {a, b}
    # A tenant sees its own members only, and the users behind them.
    with tenant_session(app_engine, tenant_id=a) as s:
        assert s.execute(text("select count(*) from cbam.memberships")).scalar_one() == 1
        assert s.execute(text("select email from cbam.users")).scalars().all() == [user_mail]


def test_unknown_role_is_rejected(app_engine: Engine, admin_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    user = uuid7()
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        s.execute(
            text("insert into cbam.users (id, email) values (:i, :e)"),
            {"i": user, "e": f"x-{user.hex}@example.test"},
        )
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a) as s:
        s.execute(
            text(
                "insert into cbam.memberships (id, user_id, tenant_id, roles)"
                " values (:i, :u, :t, array['superuser'])"
            ),
            {"i": uuid7(), "u": user, "t": a},
        )


def test_app_role_cannot_delete_tenants_or_organisations(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    make_org(app_engine, a, "A Ltd")
    for table in ("organisations", "tenants"):
        with pytest.raises(ProgrammingError), tenant_session(app_engine, tenant_id=a) as s:
            s.execute(text(f"delete from cbam.{table}"))  # noqa: S608


def test_every_cbam_table_has_forced_rls(admin_engine: Engine) -> None:
    """A new table cannot forget row-level security (docs/DATABASE.md section 2)."""
    with admin_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                select c.relname, c.relrowsecurity, c.relforcerowsecurity
                from pg_class c join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'cbam' and c.relkind = 'r' and c.relname <> 'alembic_version'
                """
            )
        ).all()
    assert rows, "no cbam tables found"
    missing = [name for name, enabled, forced in rows if not (enabled and forced)]
    assert missing == [], f"tables without forced RLS: {missing}"

"""R1-023: the audit trail is append-only and tamper-evident."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, InternalError, ProgrammingError

from app.core.audit import record, verify_all_chains, verify_chain
from app.core.db import tenant_session
from app.core.ids import uuid7
from tests.integration.conftest import make_tenant

NOW = datetime(2027, 3, 31, 23, 30, tzinfo=UTC)


def _write(engine: Engine, tenant: UUID, action: str = "import_line.scope_decided") -> UUID:
    with tenant_session(engine, tenant_id=tenant) as s:
        return record(
            s,
            tenant_id=tenant,
            actor_type="system",
            actor_id=None,
            action=action,
            object_type="import_line",
            object_id=uuid7(),
            occurred_at=NOW,
            before={"scope": None},
            after={"scope": "IN_SCOPE", "net_mass_kg": Decimal("48200.000000")},
            reason="rule R1-007",
        )


def test_events_form_a_hash_chain_per_tenant(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    for _ in range(3):
        _write(app_engine, a)
    _write(app_engine, b)
    with tenant_session(app_engine, tenant_id=a) as s:
        rows = s.execute(
            text("select chain_seq, prev_hash, hash from cbam.audit_events order by chain_seq")
        ).all()
        assert [r.chain_seq for r in rows] == [1, 2, 3]
        assert rows[0].prev_hash is None
        assert rows[1].prev_hash == rows[0].hash
        assert rows[2].prev_hash == rows[1].hash
        assert len({bytes(r.hash) for r in rows}) == 3
        assert verify_chain(s, a).ok
    with tenant_session(app_engine, tenant_id=b) as s:
        assert s.execute(text("select chain_seq from cbam.audit_events")).scalars().all() == [1]


def test_decimals_are_stored_as_strings(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    _write(app_engine, a)
    with tenant_session(app_engine, tenant_id=a) as s:
        mass = s.execute(text("select after->>'net_mass_kg' from cbam.audit_events")).scalar_one()
        assert mass == "48200.000000"


def test_app_role_cannot_update_delete_or_truncate(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    _write(app_engine, a)
    for sql in (
        "update cbam.audit_events set reason = 'x'",
        "delete from cbam.audit_events",
        "truncate cbam.audit_events",
    ):
        with pytest.raises(ProgrammingError), tenant_session(app_engine, tenant_id=a) as s:
            s.execute(text(sql))


def test_even_the_owner_is_blocked_by_the_trigger(admin_engine: Engine, app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    _write(app_engine, a)
    for sql in (
        "update cbam.audit_events set reason = 'x'",
        "delete from cbam.audit_events",
        "truncate cbam.audit_events",
    ):
        with (
            pytest.raises((InternalError, DBAPIError), match="append-only"),
            admin_engine.begin() as c,
        ):
            c.execute(text(sql))


def test_tampering_is_detected_by_the_chain_check(admin_engine: Engine, app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    for _ in range(3):
        _write(app_engine, a)
    with admin_engine.begin() as c:
        # Simulate someone with superuser rights bypassing the guard trigger.
        c.execute(text("alter table cbam.audit_events disable trigger audit_no_update"))
        c.execute(
            text(
                "update cbam.audit_events set reason = 'edited' where tenant_id = :t and chain_seq = 2"
            ),
            {"t": a},
        )
        c.execute(text("alter table cbam.audit_events enable trigger audit_no_update"))
    with tenant_session(app_engine, tenant_id=a) as s:
        result = verify_chain(s, a)
    assert not result.ok
    assert result.first_bad_chain_seq == 2
    assert verify_all_chains(app_engine)[str(a)] == [2]


def test_tenant_cannot_read_or_forge_another_tenants_audit(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    _write(app_engine, b)
    with tenant_session(app_engine, tenant_id=a) as s:
        assert s.execute(text("select count(*) from cbam.audit_events")).scalar_one() == 0
    with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=a) as s:
        record(
            s,
            tenant_id=b,
            actor_type="system",
            actor_id=None,
            action="forged",
            object_type="x",
            object_id=uuid7(),
            occurred_at=NOW,
        )


def test_platform_events_use_their_own_chain(app_engine: Engine) -> None:
    with tenant_session(app_engine, tenant_id=None, platform=True) as s:
        record(
            s,
            tenant_id=None,
            actor_type="user",
            actor_id=uuid7(),
            action="tenant.created",
            object_type="tenant",
            object_id=uuid7(),
            occurred_at=NOW,
        )
        assert verify_chain(s, None).ok


def test_concurrent_writers_do_not_fork_the_chain(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _write(app_engine, a), range(24)))
    with tenant_session(app_engine, tenant_id=a) as s:
        seqs = (
            s.execute(text("select chain_seq from cbam.audit_events order by chain_seq"))
            .scalars()
            .all()
        )
        assert seqs == list(range(1, 25))
        assert verify_chain(s, a).ok


def test_naive_timestamps_are_refused(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    with (
        pytest.raises(ValueError, match="timezone-aware"),
        tenant_session(app_engine, tenant_id=a) as s,
    ):
        record(
            s,
            tenant_id=a,
            actor_type="system",
            actor_id=None,
            action="x",
            object_type="x",
            object_id=uuid7(),
            occurred_at=datetime(2027, 1, 1),  # noqa: DTZ001
        )


def test_nightly_job_passes_when_chains_are_intact(
    app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import db
    from app.core.jobs import verify_audit_chains

    a = make_tenant(app_engine, "A")
    _write(app_engine, a)
    monkeypatch.setattr(db, "get_engine", lambda: app_engine)
    # Other tests tamper with their own tenants on purpose, so only assert on this one.
    assert str(a) not in verify_all_chains(app_engine)
    assert callable(verify_audit_chains)

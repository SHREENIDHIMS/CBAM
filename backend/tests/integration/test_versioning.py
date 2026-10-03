"""R1-045: optimistic concurrency. Two users acting on the same version: one wins, one gets 409."""

import threading
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from app.core.db import tenant_session
from app.core.errors import StaleVersionError, TenantMismatchError
from app.core.versioning import update_versioned
from tests.integration.conftest import make_org, make_tenant


def _legal_name(engine: Engine, tenant: UUID, org: UUID) -> tuple[str, int]:
    with tenant_session(engine, tenant_id=tenant) as s:
        row = s.execute(
            text("select legal_name, row_version from cbam.organisations where id = :i"),
            {"i": org},
        ).one()
        return row.legal_name, row.row_version


def test_update_increments_version(app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    org = make_org(app_engine, t, "Old")
    with tenant_session(app_engine, tenant_id=t) as s:
        new_version = update_versioned(
            s, "organisations", row_id=org, expected_version=1, values={"legal_name": "New"}
        )
    assert new_version == 2
    assert _legal_name(app_engine, t, org) == ("New", 2)


def test_stale_version_is_409_and_changes_nothing(app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    org = make_org(app_engine, t, "Old")
    with tenant_session(app_engine, tenant_id=t) as s:
        update_versioned(
            s, "organisations", row_id=org, expected_version=1, values={"legal_name": "A"}
        )
    with pytest.raises(StaleVersionError) as exc, tenant_session(app_engine, tenant_id=t) as s:
        update_versioned(
            s, "organisations", row_id=org, expected_version=1, values={"legal_name": "B"}
        )
    assert exc.value.status == 409
    assert _legal_name(app_engine, t, org) == ("A", 2)


def test_another_tenants_row_looks_like_it_does_not_exist(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    org_b = make_org(app_engine, b, "B Ltd")
    with pytest.raises(TenantMismatchError), tenant_session(app_engine, tenant_id=a) as s:
        update_versioned(
            s, "organisations", row_id=org_b, expected_version=1, values={"legal_name": "x"}
        )


def test_concurrent_approvals_one_success_one_409(app_engine: Engine) -> None:
    """Phase 1 exit gate: concurrent approval returns one success and one 409."""
    t = make_tenant(app_engine)
    org = make_org(app_engine, t, "Pending")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def approve(label: str) -> None:
        try:
            with tenant_session(app_engine, tenant_id=t) as s:
                barrier.wait(timeout=10)  # both hold version 1 before either writes
                update_versioned(
                    s,
                    "organisations",
                    row_id=org,
                    expected_version=1,
                    values={"legal_name": f"approved by {label}"},
                )
            result = "ok"
        except StaleVersionError:
            result = "409"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=approve, args=(n,)) for n in ("a", "b")]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=20)
    assert sorted(outcomes) == ["409", "ok"]
    assert _legal_name(app_engine, t, org)[1] == 2


def test_unsafe_identifiers_are_refused(app_engine: Engine) -> None:
    t = make_tenant(app_engine)
    with (
        pytest.raises(ValueError, match="identifier"),
        tenant_session(app_engine, tenant_id=t) as s,
    ):
        update_versioned(
            s,
            "organisations; drop table cbam.tenants",
            row_id=t,
            expected_version=1,
            values={"a": 1},
        )
    with (
        pytest.raises(ValueError, match="identifier"),
        tenant_session(app_engine, tenant_id=t) as s,
    ):
        update_versioned(
            s, "organisations", row_id=t, expected_version=1, values={"legal_name = 'x', id": 1}
        )
    with (
        pytest.raises(ValueError, match="row_version"),
        tenant_session(app_engine, tenant_id=t) as s,
    ):
        update_versioned(
            s, "organisations", row_id=t, expected_version=1, values={"row_version": 99}
        )

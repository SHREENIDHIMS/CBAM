"""R1-050: what the database and the service refuse (security and review findings, 3 Oct 2026)."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.cli.bootstrap_domain_owner import revoke
from app.core.db import tenant_session
from app.core.errors import InvalidRequestError, ReasonRequiredError, RuleBlockedError
from app.modules.refdata import service
from app.modules.refdata.service import Actor
from tests.integration.conftest import make_tenant, make_user, owner_session
from tests.integration.test_refdata import (  # noqa: F401
    NOW,
    activate,
    clean,
    load,
    make_owner,
    open_source,
    scalar,
    session,
)
from tests.integration.test_refdata_api import ACTIVATE, P, h
from tests.refdata_helpers import CODES_V1, write_dataset


def test_a_tenant_session_cannot_write_platform_tables(app_engine: Engine) -> None:
    tenant = make_tenant(app_engine)
    for sql in (
        "insert into cbam.regulatory_sources (id, source_id, title, source_type, status)"
        " values (gen_random_uuid(), 'X', 'x', 'guidance', 'draft')",
        "insert into cbam.ref_datasets (id, name) values (gen_random_uuid(), 'x')",
    ):
        with pytest.raises(DBAPIError), tenant_session(app_engine, tenant_id=tenant) as s:
            s.execute(text(sql))


def test_a_tenant_session_cannot_forge_an_impact_report(app_engine: Engine, tmp_path: Path) -> None:
    result = load(app_engine, write_dataset(tmp_path))
    tenant = make_tenant(app_engine)
    with tenant_session(app_engine, tenant_id=tenant) as s:
        updated = s.execute(
            text("update cbam.ref_dataset_versions set impact_report = '{}'::jsonb where id = :i"),
            {"i": result.version_id},
        ).rowcount
    assert updated == 0
    assert scalar(app_engine, "select impact_report is null from cbam.ref_dataset_versions") is True


def test_the_database_refuses_activation_without_a_matching_report(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    result = load(app_engine, write_dataset(tmp_path))
    activate_sql = (
        "update cbam.ref_dataset_versions set status = 'active', activated_by = :u,"
        " activated_at = now() where id = :i"
    )
    with pytest.raises(DBAPIError, match="impact report"), session(app_engine, owner) as s:
        s.execute(text(activate_sql), {"u": owner, "i": result.version_id})
    forged = '{"version_id": "x", "checksum_sha256": "y", "compared_to": null}'
    with session(app_engine, owner) as s:
        s.execute(
            text("update cbam.ref_dataset_versions set impact_report = cast(:r as jsonb)"),
            {"r": forged},
        )
    with pytest.raises(DBAPIError, match="impact report"), session(app_engine, owner) as s:
        s.execute(text(activate_sql), {"u": owner, "i": result.version_id})


def test_only_a_domain_owner_can_record_an_impact_report(
    app_engine: Engine, tmp_path: Path
) -> None:
    load(app_engine, write_dataset(tmp_path))
    with (
        pytest.raises(DBAPIError, match="domain owner"),
        session(app_engine, make_user(app_engine)) as s,
    ):
        s.execute(text("update cbam.ref_dataset_versions set impact_report = '{}'::jsonb"))


def test_rows_cannot_be_added_once_the_report_was_made(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    result = load(app_engine, write_dataset(tmp_path))
    with session(app_engine, owner) as s:
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.1")
    with pytest.raises(DBAPIError, match="impact report"), session(app_engine) as s:
        s.execute(
            text(
                "insert into cbam.ref_cbam_commodity_codes (id, dataset_version_id,"
                " effective_from, code_prefix, listing_text, sector, description, in_scope)"
                " values (gen_random_uuid(), :v, '2027-01-01', '99', '99', 'x', 'x', true)"
            ),
            {"v": result.version_id},
        )


def test_an_empty_version_cannot_be_activated(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    header = CODES_V1.splitlines()[0] + "\n"
    load(app_engine, write_dataset(tmp_path, csv=header))
    with session(app_engine, owner) as s:
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.1")
        version = service.get_version(s, "cbam_commodity_codes", "t.1")
        with pytest.raises(RuleBlockedError, match="empty"):
            service.activate_version(
                s,
                Actor(owner),
                NOW,
                "cbam_commodity_codes",
                "t.1",
                expected_version=version["row_version"],
                app_env="local",
                reason="x",
                acknowledge_warnings=True,
            )


def test_activation_needs_a_reason_and_acknowledged_warnings(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    with session(app_engine, owner) as s:
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.1")
        version = service.get_version(s, "cbam_commodity_codes", "t.1")
        assert version["impact_report"]["warnings"]  # fixture and not-yet-in-force source
        kwargs = {"expected_version": version["row_version"], "app_env": "local"}
        with pytest.raises(ReasonRequiredError):
            service.activate_version(
                s,
                Actor(owner),
                NOW,
                "cbam_commodity_codes",
                "t.1",
                reason=" ",
                acknowledge_warnings=True,
                **kwargs,
            )
        with pytest.raises(RuleBlockedError, match="warnings"):
            service.activate_version(
                s,
                Actor(owner),
                NOW,
                "cbam_commodity_codes",
                "t.1",
                reason="Reviewed",
                **kwargs,
            )
        done = service.activate_version(
            s,
            Actor(owner),
            NOW,
            "cbam_commodity_codes",
            "t.1",
            reason="Reviewed the list",
            acknowledge_warnings=True,
            **kwargs,
        )
    assert done["status"] == "active"
    reason = scalar(
        app_engine,
        "select reason from cbam.audit_events where action = 'refdata.version_activated'"
        " order by occurred_at desc, chain_seq desc limit 1",
    )
    assert reason == "Reviewed the list"


def test_the_report_changes_the_row_version(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    with session(app_engine, owner) as s:
        before = service.get_version(s, "cbam_commodity_codes", "t.1")["row_version"]
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.1")
        after = service.get_version(s, "cbam_commodity_codes", "t.1")["row_version"]
    assert after == before + 1


def test_the_database_keeps_source_status_one_way(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    open_source(app_engine, owner)  # in_force

    def run(sql: str, match: str) -> None:
        with pytest.raises(DBAPIError, match=match), session(app_engine, owner) as s:
            s.execute(text(sql))

    run("update cbam.regulatory_sources set status = 'draft'", "cannot go from")
    run("update cbam.regulatory_sources set status = 'laid'", "cannot go from")
    run("update cbam.regulatory_sources set status = 'superseded'", "stopped applying")
    run("update cbam.regulatory_sources set commencement_date = '2020-01-01'", "together with")
    run("update cbam.regulatory_sources set title = 'renamed'", "together with")
    # a superseded source needs its end date and then never moves again
    with session(app_engine, owner) as s:
        s.execute(
            text(
                "update cbam.regulatory_sources set status = 'superseded',"
                " effective_to = '2028-01-01'"
            )
        )
    run("update cbam.regulatory_sources set status = 'in_force'", "cannot go from")


def test_superseding_a_source_needs_an_end_date_and_keeps_earlier_dates(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    activate(app_engine, owner, "t.1")
    open_source(app_engine, owner)
    with session(app_engine, owner) as s:
        source = service.get_source(s, "TEST-SOURCE")
        with pytest.raises(InvalidRequestError, match="effective_to"):
            service.set_source_status(
                s,
                Actor(owner),
                NOW,
                "TEST-SOURCE",
                expected_version=source["row_version"],
                status="superseded",
                reason="Replaced",
            )
        service.set_source_status(
            s,
            Actor(owner),
            NOW,
            "TEST-SOURCE",
            expected_version=source["row_version"],
            status="superseded",
            reason="Replaced",
            effective_to=date(2027, 7, 1),
        )
        replay = service.get(s, "cbam_commodity_codes", {"code_prefix": "72"}, on=date(2027, 6, 30))
        later = service.get(s, "cbam_commodity_codes", {"code_prefix": "72"}, on=date(2027, 7, 1))
    assert replay is not None and later is None


def test_a_manifest_that_redescribes_a_registered_source_is_refused(
    app_engine: Engine, tmp_path: Path
) -> None:
    load(app_engine, write_dataset(tmp_path / "a"))
    other = write_dataset(tmp_path / "b", version="t.2")
    manifest = other / "manifest.yaml"
    manifest.write_text(manifest.read_text().replace("Test source (not law)", "A different title"))
    with pytest.raises(RuleBlockedError, match="different details"):
        load(app_engine, other)


def test_rows_outside_the_manifest_period_are_refused(app_engine: Engine, tmp_path: Path) -> None:
    csv = "service,opening_date,effective_from,effective_to\nregistration,2028-01-01,2020-01-01,\n"
    folder = write_dataset(tmp_path, dataset="service_state", csv=csv)
    with pytest.raises(InvalidRequestError, match="outside the manifest"):
        load(app_engine, folder)


def test_nan_and_oversized_numbers_are_refused(app_engine: Engine, tmp_path: Path) -> None:
    header = "threshold_gbp,forward_days,backward_months,backward_test_day,lookback_floor_date,warning_ratio\n"
    for row, match in (
        ("NaN,30,12,1,,0.8\n", "finite"),
        ("Infinity,30,12,1,,0.8\n", "finite"),
        ("50000,99999999999,12,1,,0.8\n", "out of range"),
    ):
        folder = write_dataset(tmp_path / match, dataset="threshold_rules", csv=header + row)
        with pytest.raises(InvalidRequestError, match=match):
            load(app_engine, folder)


def test_a_list_with_a_nested_or_orphan_exception_is_refused(
    app_engine: Engine, tmp_path: Path
) -> None:
    orphan = CODES_V1 + "9999,Except 9999,x,Orphan,,false,99\n"
    with pytest.raises(InvalidRequestError, match="must sit under"):
        load(app_engine, write_dataset(tmp_path / "a", csv=orphan))
    nested = CODES_V1 + "720499,720499,iron_and_steel,Nested in scope,,true,\n"
    with pytest.raises(InvalidRequestError, match="sits under an exception"):
        load(app_engine, write_dataset(tmp_path / "b", csv=nested))


def test_revoking_or_disabling_a_domain_owner_removes_access(
    client: TestClient, app_engine: Engine, admin_engine: Engine
) -> None:
    owner = make_owner(app_engine, admin_engine)
    assert client.get(f"{P}/datasets", headers=h(owner)).status_code == 200
    with owner_session(admin_engine) as conn:
        conn.execute(text("update cbam.users set status = 'disabled' where id = :u"), {"u": owner})
    assert client.get(f"{P}/datasets", headers=h(owner)).status_code == 403
    with owner_session(admin_engine) as conn:
        conn.execute(text("update cbam.users set status = 'active' where id = :u"), {"u": owner})
    assert client.get(f"{P}/datasets", headers=h(owner)).status_code == 200
    assert revoke(admin_engine, user_id=owner, now=NOW) is True
    assert client.get(f"{P}/datasets", headers=h(owner)).status_code == 403
    assert revoke(admin_engine, user_id=owner, now=NOW) is False


def test_activation_needs_a_reason_over_the_api(
    client: TestClient, app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    url = f"{P}/datasets/cbam_commodity_codes/versions/t.1"
    assert client.post(f"{url}/impact", headers=h(owner)).status_code == 200
    etag = client.get(url, headers=h(owner)).headers["etag"]
    missing = client.post(f"{url}/activate", headers={**h(owner), "If-Match": etag}, json={})
    assert missing.status_code == 422
    unacknowledged = client.post(
        f"{url}/activate", headers={**h(owner), "If-Match": etag}, json={"reason": "ok"}
    )
    assert unacknowledged.status_code == 409 and "warnings" in unacknowledged.json()["detail"]
    ok = client.post(f"{url}/activate", headers={**h(owner), "If-Match": etag}, json=ACTIVATE)
    assert ok.status_code == 200

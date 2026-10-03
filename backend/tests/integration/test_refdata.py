"""R1-050 reference-data loader, activation and lookups against PostgreSQL.

Sources: docs/DATABASE.md sections 5-6, docs/TECHNICAL_SPEC.md section 6, CLAUDE.md rules 1, 2,
4, 8 and 17. Datasets here are test fixtures (`fixture: true`), not law.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.audit import verify_chain
from app.core.db import tenant_session
from app.core.errors import (
    InvalidRequestError,
    NotPermittedError,
    ReasonRequiredError,
    RuleBlockedError,
    StaleVersionError,
)
from app.modules.refdata import rules, service
from app.modules.refdata.datasets import DATASETS
from app.modules.refdata.load import load_dataset
from app.modules.refdata.service import Actor, AffectedItem
from tests.integration.conftest import make_user
from tests.refdata_helpers import CODES_V1, FIXTURES, write_dataset

NOW = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
D = date(2027, 6, 1)
ALL_TABLES = [
    *(f"ref_{name}" for name in DATASETS),
    "ref_dataset_versions",
    "ref_datasets",
    "regulatory_sources",
    "platform_domain_owners",
]


@pytest.fixture(autouse=True)
def clean(admin_engine: Engine) -> Iterator[None]:
    """The test database persists between runs; reference data is global, so reset it."""
    with admin_engine.begin() as conn:
        conn.execute(text("set local session_replication_role = replica"))
        for table in ALL_TABLES:
            conn.execute(text(f"delete from cbam.{table}"))  # noqa: S608
    service.clear_impact_providers()
    yield
    service.clear_impact_providers()


def session(engine: Engine, user: UUID | None = None):  # type: ignore[no-untyped-def]
    return tenant_session(engine, tenant_id=None, user_id=user, platform=True)


def make_owner(app_engine: Engine, admin_engine: Engine) -> UUID:
    uid = make_user(app_engine)
    with admin_engine.begin() as conn:
        conn.execute(
            text("insert into cbam.platform_domain_owners (user_id) values (:u)"), {"u": uid}
        )
    return uid


def load(engine: Engine, folder: Path, *, env: str = "local", now: datetime = NOW):  # type: ignore[no-untyped-def]
    with session(engine) as s:
        return load_dataset(s, folder, now=now, app_env=env)


def scalar(engine: Engine, sql: str, **params: object) -> object:
    with session(engine) as s:
        return s.execute(text(sql), params).scalar()


def audit_count(engine: Engine, action: str | None = None) -> int:
    sql = "select count(*) from cbam.audit_events where tenant_id is null"
    if action:
        sql += f" and action = '{action}'"
    return int(scalar(engine, sql))  # type: ignore[call-overload]


def open_source(engine: Engine, owner: UUID, source_id: str = "TEST-SOURCE", **kw: object) -> None:
    """Make the source in force, as a domain owner would."""
    with session(engine, owner) as s:
        current = service.get_source(s, source_id)
        service.set_source_status(
            s,
            Actor(owner),
            NOW,
            source_id,
            expected_version=current["row_version"],
            status=str(kw.get("status", "in_force")),
            reason="Primary text read",
            commencement_date=kw.get("commencement_date"),  # type: ignore[arg-type]
        )


def activate(
    engine: Engine, owner: UUID, version: str, dataset: str = "cbam_commodity_codes"
) -> dict:  # type: ignore[type-arg]
    with session(engine, owner) as s:
        service.build_impact_report(s, Actor(owner), NOW, dataset, version)
    with session(engine, owner) as s:
        current = service.get_version(s, dataset, version)
        return service.activate_version(
            s,
            Actor(owner),
            NOW,
            dataset,
            version,
            expected_version=current["row_version"],
            app_env="local",
        )


# --- the loader --------------------------------------------------------------------------


def test_every_fixture_dataset_loads_so_the_specs_match_the_migration(
    app_engine: Engine,
) -> None:
    folders = sorted(p for p in FIXTURES.glob("*/*") if p.is_dir())
    assert {p.parent.name for p in folders} == set(DATASETS)
    for folder in folders:
        assert load(app_engine, folder).status == "loaded"
    # the dataset specs list exactly the migration's business columns
    with session(app_engine) as s:
        for spec in DATASETS.values():
            cols = set(
                s.execute(
                    text(
                        "select column_name from information_schema.columns"
                        " where table_schema = 'cbam' and table_name = :t"
                    ),
                    {"t": spec.table},
                ).scalars()
            )
            assert cols == {
                "id",
                "dataset_version_id",
                "effective_from",
                "effective_to",
                *spec.column_names,
            }


def test_loaded_versions_are_pending_and_audited(app_engine: Engine, tmp_path: Path) -> None:
    loaded_before = audit_count(app_engine, "refdata.version_loaded")
    registered_before = audit_count(app_engine, "refdata.source_registered")
    result = load(app_engine, write_dataset(tmp_path))
    assert (result.status, result.row_count) == ("loaded", 3)
    row = scalar(
        app_engine,
        "select status from cbam.ref_dataset_versions where id = :i",
        i=result.version_id,
    )
    assert row == "pending"
    assert audit_count(app_engine, "refdata.version_loaded") == loaded_before + 1
    assert audit_count(app_engine, "refdata.source_registered") == registered_before + 1
    with session(app_engine) as s:
        assert verify_chain(s, None).ok


def test_reloading_the_same_folder_changes_nothing(app_engine: Engine, tmp_path: Path) -> None:
    folder = write_dataset(tmp_path)
    first = load(app_engine, folder)
    audits = audit_count(app_engine)
    again = load(app_engine, folder)
    assert (again.status, again.version_id) == ("unchanged", first.version_id)
    assert audit_count(app_engine) == audits
    assert scalar(app_engine, "select count(*) from cbam.ref_cbam_commodity_codes") == 3
    assert scalar(app_engine, "select count(*) from cbam.ref_dataset_versions") == 1


def test_a_tampered_data_file_is_refused(app_engine: Engine, tmp_path: Path) -> None:
    folder = write_dataset(tmp_path)
    (folder / "data.csv").write_text(CODES_V1.replace("Iron and steel", "Iron and steel (edited)"))
    with pytest.raises(InvalidRequestError, match="checksum"):
        load(app_engine, folder)
    assert scalar(app_engine, "select count(*) from cbam.ref_dataset_versions") == 0


def test_same_version_with_different_content_is_refused(app_engine: Engine, tmp_path: Path) -> None:
    load(app_engine, write_dataset(tmp_path / "a"))
    changed = write_dataset(tmp_path / "b", csv=CODES_V1.replace("Hydrogen", "Hydrogen gas"))
    with pytest.raises(RuleBlockedError, match="new version"):
        load(app_engine, changed)
    assert scalar(app_engine, "select count(*) from cbam.ref_cbam_commodity_codes") == 3


def test_fixture_datasets_cannot_be_loaded_in_production(
    app_engine: Engine, tmp_path: Path
) -> None:
    with pytest.raises(RuleBlockedError, match="production"):
        load(app_engine, write_dataset(tmp_path), env="production")


def test_a_bad_row_loads_nothing(app_engine: Engine, tmp_path: Path) -> None:
    bad = write_dataset(tmp_path, csv=CODES_V1.replace("true,\n7204", "maybe,\n7204"))
    with pytest.raises(InvalidRequestError, match="row 2, in_scope"):
        load(app_engine, bad)
    assert scalar(app_engine, "select count(*) from cbam.ref_datasets") == 0


def test_the_loader_registers_a_source_as_draft_or_laid_only(
    app_engine: Engine, tmp_path: Path
) -> None:
    load(app_engine, write_dataset(tmp_path, source_status="draft"))
    assert scalar(app_engine, "select status from cbam.regulatory_sources") == "draft"
    # a later manifest cannot move the registry: the registry is the authority
    load(app_engine, write_dataset(tmp_path, version="t.2", source_status="laid"))
    assert scalar(app_engine, "select status from cbam.regulatory_sources") == "draft"


# --- immutability and guards ------------------------------------------------------------


def test_loaded_rows_cannot_be_changed_or_deleted(app_engine: Engine, tmp_path: Path) -> None:
    load(app_engine, write_dataset(tmp_path))
    for sql in (
        "update cbam.ref_cbam_commodity_codes set in_scope = false",
        "delete from cbam.ref_cbam_commodity_codes",
        "truncate cbam.ref_cbam_commodity_codes",
        "delete from cbam.ref_dataset_versions",
        "delete from cbam.regulatory_sources",
    ):
        with pytest.raises(DBAPIError), session(app_engine) as s:
            s.execute(text(sql))


def test_rows_cannot_be_added_to_an_active_version(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    result = load(app_engine, write_dataset(tmp_path))
    open_source(app_engine, owner)
    activate(app_engine, owner, "t.1")
    with pytest.raises(DBAPIError, match="pending"), session(app_engine) as s:
        s.execute(
            text(
                "insert into cbam.ref_cbam_commodity_codes (id, dataset_version_id, effective_from,"
                " code_prefix, listing_text, sector, description, in_scope)"
                " values (gen_random_uuid(), :v, '2027-01-01', '99', '99', 'x', 'x', true)"
            ),
            {"v": result.version_id},
        )


def test_overlapping_rows_are_refused_by_the_database_too(
    app_engine: Engine, tmp_path: Path
) -> None:
    result = load(app_engine, write_dataset(tmp_path))
    with pytest.raises(DBAPIError, match="no_overlap"), session(app_engine) as s:
        s.execute(
            text(
                "insert into cbam.ref_cbam_commodity_codes (id, dataset_version_id, effective_from,"
                " code_prefix, listing_text, sector, description, in_scope)"
                " values (gen_random_uuid(), :v, '2027-06-01', '72', '72', 'x', 'x', true)"
            ),
            {"v": result.version_id},
        )


def test_a_non_owner_cannot_activate_even_with_direct_sql(
    app_engine: Engine, tmp_path: Path
) -> None:
    result = load(app_engine, write_dataset(tmp_path))
    someone = make_user(app_engine)
    with pytest.raises(DBAPIError, match="domain owner"), session(app_engine, someone) as s:
        s.execute(
            text(
                "update cbam.ref_dataset_versions set status = 'active', activated_by = :u,"
                " activated_at = now() where id = :i"
            ),
            {"u": someone, "i": result.version_id},
        )


def test_a_domain_owner_cannot_record_someone_elses_approval(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    result = load(app_engine, write_dataset(tmp_path))
    with pytest.raises(DBAPIError, match="who approved"), session(app_engine, owner) as s:
        s.execute(
            text(
                "update cbam.ref_dataset_versions set status = 'active', activated_by = :u,"
                " activated_at = now() where id = :i"
            ),
            {"u": make_user(app_engine), "i": result.version_id},
        )


def test_the_app_role_cannot_grant_domain_owner(app_engine: Engine) -> None:
    uid = make_user(app_engine)
    with pytest.raises(DBAPIError), session(app_engine) as s:
        s.execute(text("insert into cbam.platform_domain_owners (user_id) values (:u)"), {"u": uid})


# --- activation rule ---------------------------------------------------------------------


def get_code(engine: Engine, code: str, on: date = D):  # type: ignore[no-untyped-def]
    with session(engine) as s:
        return service.get(s, "cbam_commodity_codes", {"code_prefix": code}, on=on)


def test_a_pending_version_is_never_returned(app_engine: Engine, tmp_path: Path) -> None:
    load(app_engine, write_dataset(tmp_path))
    assert get_code(app_engine, "72") is None


def test_a_draft_source_cannot_drive_a_lookup_even_when_the_version_is_active(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    """Exit gate: a draft source's data cannot be returned by any get()."""
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path, source_status="draft"))
    activate(app_engine, owner, "t.1")
    assert scalar(app_engine, "select status from cbam.ref_dataset_versions") == "active"
    assert get_code(app_engine, "72") is None
    with session(app_engine) as s:
        assert (
            service.snapshot(s, ["cbam_commodity_codes"], on=D).rows["cbam_commodity_codes"] == ()
        )
        assert service.get_by_prefix(s, "cbam_commodity_codes", "7201", on=D) is None
    # once the domain owner puts the source in force, the same data is served
    open_source(app_engine, owner)
    assert get_code(app_engine, "72") is not None


@pytest.mark.parametrize(
    ("start", "moves", "commencement", "on", "usable"),
    [
        ("draft", (), None, date(2027, 6, 1), False),
        ("laid", (), None, date(2027, 6, 1), False),
        ("laid", ("in_force",), None, date(2027, 6, 1), True),
        ("draft", ("commenced",), None, date(2027, 6, 1), True),
        ("laid", ("in_force",), date(2027, 6, 1), date(2027, 6, 1), True),
        ("laid", ("in_force",), date(2027, 6, 2), date(2027, 6, 1), False),
        ("laid", ("in_force",), None, date(2026, 12, 31), False),  # before the row's period
        ("laid", ("in_force", "superseded"), None, date(2027, 6, 1), False),
    ],
)
def test_the_sql_view_and_the_pure_rule_agree(
    app_engine: Engine,
    admin_engine: Engine,
    tmp_path: Path,
    start: str,
    moves: tuple[str, ...],
    commencement: date | None,
    on: date,
    usable: bool,
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(
        app_engine,
        write_dataset(tmp_path, source_status=start, commencement_date=commencement),
    )
    activate(app_engine, owner, "t.1")
    for status in moves:
        open_source(app_engine, owner, status=status)
    served = get_code(app_engine, "72", on) is not None
    current = scalar(app_engine, "select status from cbam.regulatory_sources")
    decision = rules.source_usable(
        source_id="TEST-SOURCE",
        status=str(current),
        commencement_date=commencement,
        effective_from=None,
        effective_to=None,
        on=on,
    )
    row_open = on >= date(2027, 1, 1)  # the dataset's own effective_from
    assert served is (decision.outcome == "ACTIVE" and row_open)
    assert served is usable


def test_lookups_use_the_legal_date_and_the_longest_listed_prefix(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    open_source(app_engine, owner)
    activate(app_engine, owner, "t.1")
    assert get_code(app_engine, "72", date(2026, 12, 31)) is None
    with session(app_engine) as s:
        in_scope = service.get_by_prefix(s, "cbam_commodity_codes", "7201100000", on=D)
        excepted = service.get_by_prefix(s, "cbam_commodity_codes", "7204100000", on=D)
        assert in_scope and in_scope["in_scope"] is True and in_scope["code_prefix"] == "72"
        assert excepted and excepted["in_scope"] is False and excepted["exclusion_within"] == "72"
        assert service.get_by_prefix(s, "cbam_commodity_codes", "9999000000", on=D) is None
        with pytest.raises(InvalidRequestError):
            service.get_by_prefix(s, "cbam_commodity_codes", "72 04", on=D)
        with pytest.raises(InvalidRequestError):
            service.get(s, "cbam_commodity_codes", {"wrong": "x"}, on=D)


def test_a_snapshot_names_the_versions_it_came_from(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    result = load(app_engine, write_dataset(tmp_path))
    open_source(app_engine, owner)
    activate(app_engine, owner, "t.1")
    with session(app_engine) as s:
        snap = service.snapshot(s, ["cbam_commodity_codes", "threshold_rules"], on=D)
    assert snap.version_ids == (result.version_id,)
    assert len(snap.rows["cbam_commodity_codes"]) == 3 and snap.rows["threshold_rules"] == ()


# --- activation workflow -----------------------------------------------------------------


def test_activation_needs_an_impact_report_first(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    with session(app_engine, owner) as s:
        version = service.get_version(s, "cbam_commodity_codes", "t.1")
        with pytest.raises(RuleBlockedError, match="impact report"):
            service.activate_version(
                s,
                Actor(owner),
                NOW,
                "cbam_commodity_codes",
                "t.1",
                expected_version=version["row_version"],
                app_env="local",
            )


def test_only_a_domain_owner_can_activate_or_set_a_source_status(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    outsider = make_user(app_engine)
    load(app_engine, write_dataset(tmp_path))
    with session(app_engine, outsider) as s:
        version = service.get_version(s, "cbam_commodity_codes", "t.1")
        source = service.get_source(s, "TEST-SOURCE")
        with pytest.raises(NotPermittedError):
            service.activate_version(
                s,
                Actor(outsider),
                NOW,
                "cbam_commodity_codes",
                "t.1",
                expected_version=version["row_version"],
                app_env="local",
            )
        with pytest.raises(NotPermittedError):
            service.set_source_status(
                s,
                Actor(outsider),
                NOW,
                "TEST-SOURCE",
                expected_version=source["row_version"],
                status="in_force",
                reason="x",
            )
    assert owner  # the owner path is covered by the other tests


def test_activation_retires_the_previous_version_and_keeps_it(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    retired_before = audit_count(app_engine, "refdata.version_retired")
    activated_before = audit_count(app_engine, "refdata.version_activated")
    load(app_engine, write_dataset(tmp_path))
    open_source(app_engine, owner)
    activate(app_engine, owner, "t.1")
    load(
        app_engine,
        write_dataset(tmp_path, version="t.2", csv=CODES_V1.replace("Hydrogen", "Hydrogen gas")),
    )
    activate(app_engine, owner, "t.2")
    with session(app_engine) as s:
        statuses = {
            v["version"]: v["status"] for v in service.list_versions(s, "cbam_commodity_codes")
        }
    assert statuses == {"t.1": "retired", "t.2": "active"}
    served = get_code(app_engine, "2804")
    assert served and served["description"] == "Hydrogen gas" and served["dataset_version"] == "t.2"
    # the retired rows are still stored, so a decision that recorded t.1 can be replayed
    assert scalar(app_engine, "select count(*) from cbam.ref_cbam_commodity_codes") == 6
    assert audit_count(app_engine, "refdata.version_retired") == retired_before + 1
    assert audit_count(app_engine, "refdata.version_activated") == activated_before + 2
    with session(app_engine) as s:
        assert verify_chain(s, None).ok


def test_activation_checks_the_row_version_and_the_status(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    with session(app_engine, owner) as s:
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.1")
    with session(app_engine, owner) as s, pytest.raises(StaleVersionError):
        service.activate_version(
            s,
            Actor(owner),
            NOW,
            "cbam_commodity_codes",
            "t.1",
            expected_version=99,
            app_env="local",
        )
    activate(app_engine, owner, "t.1")
    with session(app_engine, owner) as s:
        version = service.get_version(s, "cbam_commodity_codes", "t.1")
        with pytest.raises(RuleBlockedError, match="pending"):
            service.activate_version(
                s,
                Actor(owner),
                NOW,
                "cbam_commodity_codes",
                "t.1",
                expected_version=version["row_version"],
                app_env="local",
            )


def test_a_stale_impact_report_blocks_activation(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    load(app_engine, write_dataset(tmp_path, version="t.2", csv=CODES_V1.replace("Hydrogen", "H2")))
    with session(app_engine, owner) as s:  # report for t.2 is made against "nothing active"
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.2")
    activate(app_engine, owner, "t.1")  # now t.1 is active
    with session(app_engine, owner) as s:
        version = service.get_version(s, "cbam_commodity_codes", "t.2")
        with pytest.raises(RuleBlockedError, match="generate it again"):
            service.activate_version(
                s,
                Actor(owner),
                NOW,
                "cbam_commodity_codes",
                "t.2",
                expected_version=version["row_version"],
                app_env="local",
            )


def test_fixture_datasets_cannot_be_activated_in_production(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    with session(app_engine, owner) as s:
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.1")
        version = service.get_version(s, "cbam_commodity_codes", "t.1")
        with pytest.raises(RuleBlockedError, match="production"):
            service.activate_version(
                s,
                Actor(owner),
                NOW,
                "cbam_commodity_codes",
                "t.1",
                expected_version=version["row_version"],
                app_env="production",
            )


# --- impact report -----------------------------------------------------------------------


def test_the_impact_report_lists_the_changed_codes_and_the_affected_lines(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    """Exit gate: the report lists affected lines for a changed code list (fixture lines)."""
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    open_source(app_engine, owner)
    activate(app_engine, owner, "t.1")

    fixture_lines = {"LINE-1": "7204100000", "LINE-2": "7201100000", "LINE-3": "2804100000"}

    def provider(_: object, diff: rules.VersionDiff) -> list[AffectedItem]:
        changed = [str(c.key["code_prefix"]) for c in diff.changes]
        return [
            AffectedItem("import_line", ref, f"code {code} falls under {prefix}")
            for ref, code in fixture_lines.items()
            for prefix in changed
            if code.startswith(prefix)
        ]

    service.register_impact_provider("cbam_commodity_codes", provider)
    # t.2 drops the 7204 exception and adds a new heading
    changed_csv = (
        CODES_V1.replace("7204,Except 7204,iron_and_steel,Ferrous waste and scrap,,false,72\n", "")
        + "7601,7601,aluminium,Unwrought aluminium,Carbon dioxide,true,\n"
    )
    load(app_engine, write_dataset(tmp_path, version="t.2", csv=changed_csv))
    with session(app_engine, owner) as s:
        report = service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.2")
    assert report["rows"] == {"added": 1, "removed": 1, "changed": 0, "unchanged": 2}
    assert {c["change"]: c["key"]["code_prefix"] for c in report["changes"]} == {
        "removed": "7204",
        "added": "7601",
    }
    assert report["affected"]["count"] == 1
    assert report["affected"]["items"][0] == {
        "kind": "import_line",
        "ref": "LINE-1",
        "detail": "code 7204100000 falls under 7204",
    }
    assert report["compared_to"]["version"] == "t.1"
    assert report["source"]["outcome"] == "ACTIVE"
    # the report is stored on the version, and generating it changed no served data
    stored = scalar(
        app_engine,
        "select impact_report is not null from cbam.ref_dataset_versions where version = 't.2'",
    )
    assert stored is True
    assert get_code(app_engine, "7204")["description"] == "Ferrous waste and scrap"  # type: ignore[index]


def test_the_impact_report_warns_about_coverage_gaps_fixtures_and_drafts(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    activate(app_engine, owner, "t.1")
    load(app_engine, write_dataset(tmp_path, version="t.2", effective_from=date(2027, 7, 1)))
    with session(app_engine, owner) as s:
        report = service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.2")
    assert len(report["coverage_gaps"]) == 3
    joined = " ".join(report["warnings"])
    assert "does not cover" in joined and "fixture" in joined and "not allow" in joined
    assert report["source"]["outcome"] == "NOT_ACTIVE"


def test_only_a_pending_version_has_an_impact_report(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    load(app_engine, write_dataset(tmp_path))
    activate(app_engine, owner, "t.1")
    with session(app_engine, owner) as s, pytest.raises(RuleBlockedError, match="pending"):
        service.build_impact_report(s, Actor(owner), NOW, "cbam_commodity_codes", "t.1")


# --- source registry ---------------------------------------------------------------------


def test_source_status_changes_forward_with_a_reason_and_an_audit_event(
    app_engine: Engine, admin_engine: Engine, tmp_path: Path
) -> None:
    owner = make_owner(app_engine, admin_engine)
    changed_before = audit_count(app_engine, "refdata.source_status_changed")
    load(app_engine, write_dataset(tmp_path))
    with session(app_engine, owner) as s:
        source = service.get_source(s, "TEST-SOURCE")
        with pytest.raises(ReasonRequiredError):
            service.set_source_status(
                s,
                Actor(owner),
                NOW,
                "TEST-SOURCE",
                expected_version=source["row_version"],
                status="in_force",
                reason=None,
            )
    open_source(app_engine, owner, commencement_date=date(2027, 1, 1))
    with session(app_engine, owner) as s:
        source = service.get_source(s, "TEST-SOURCE")
        assert (source["status"], source["commencement_date"], source["row_version"]) == (
            "in_force",
            date(2027, 1, 1),
            2,
        )
        with pytest.raises(RuleBlockedError):  # never back to draft or laid
            service.set_source_status(
                s,
                Actor(owner),
                NOW,
                "TEST-SOURCE",
                expected_version=2,
                status="laid",
                reason="oops",
            )
        with pytest.raises(StaleVersionError):
            service.set_source_status(
                s,
                Actor(owner),
                NOW,
                "TEST-SOURCE",
                expected_version=1,
                status="superseded",
                reason="x",
            )
    assert audit_count(app_engine, "refdata.source_status_changed") == changed_before + 1


def test_a_source_cannot_be_registered_in_force_by_the_loader_path(app_engine: Engine) -> None:
    with pytest.raises(DBAPIError, match="domain owner"), session(app_engine) as s:
        s.execute(
            text(
                "insert into cbam.regulatory_sources (id, source_id, title, source_type, status)"
                " values (gen_random_uuid(), 'X', 'x', 'guidance', 'in_force')"
            )
        )


def test_the_checked_in_fixture_folders_are_valid_and_marked_as_fixtures() -> None:
    for manifest in FIXTURES.glob("*/*/manifest.yaml"):
        assert "fixture: true" in manifest.read_text(), manifest

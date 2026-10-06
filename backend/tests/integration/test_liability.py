# ruff: noqa: F811, S608 - imported pytest fixtures are test arguments; SQL text is test-only
"""R1-036 liable-person determination: rules are reference data, nothing is guessed.

Scenario IDs LP-20 to LP-35. Product rules, not law: the rule rows are the fixture dataset
`liable_person_rules/fixture.1` whose outcomes are invented (LEGAL-DEC-019 is open).
"""

import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.db import tenant_session
from app.core.errors import RuleBlockedError, TenantMismatchError
from app.core.storage import InMemoryStore
from app.modules.liability import service
from app.modules.tasks.service import Actor
from tests.integration.conftest import make_tenant
from tests.integration.refdata_setup import activate, load
from tests.integration.test_import_processing import (  # noqa: F401
    NOW,
    client,
    good_row,
    layout,
    queued,
    receive,
    run,
    store,
    to_csv,
    user_for,
)
from tests.refdata_helpers import FIXTURES

ACTOR = Actor("system", None)
IMPORTER = "GB123456789012"
FORWARDER = "GB210987654321"
AGENT = "GB333333333333"


def fixture_rules_active(engine: Engine, owner: UUID) -> None:
    load(engine, FIXTURES / "liable_person_rules" / "fixture.1")
    activate(engine, owner, "liable_person_rules", "fixture.1")


def seed_batch(engine: Engine, store: InMemoryStore, tenant: UUID) -> UUID:
    batch = receive(engine, store, tenant, to_csv([good_row(1)]))
    assert run(engine, store, tenant, batch.id) == "completed"
    return batch.id


def party(s, tenant: UUID, eori: str | None) -> UUID | None:  # type: ignore[no-untyped-def]
    if eori is None:
        return None
    found = s.execute(
        text("select id from cbam.parties where tenant_id = :t and eori = :e"),
        {"t": tenant, "e": eori},
    ).scalar()
    if found:
        return found
    pid = uuid4()
    s.execute(
        text("insert into cbam.parties (id, tenant_id, eori) values (:i, :t, :e)"),
        {"i": pid, "t": tenant, "e": eori},
    )
    return pid


def declaration(  # type: ignore[no-untyped-def]
    engine: Engine,
    tenant: UUID,
    batch: UUID,
    mrn: str,
    *,
    importer: str | None = IMPORTER,
    declarant: str | None = None,
    representative: str | None = None,
    kind: str = "self",
    version: int = 1,
    supersedes: UUID | None = None,
    source: str | None = "declared",
) -> UUID:
    did = uuid4()
    with tenant_session(engine, tenant_id=tenant) as s:
        s.execute(
            text(
                "insert into cbam.declarations (id, tenant_id, mrn, version, supersedes_id,"
                " acceptance_date, importer_party_id, declarant_party_id,"
                " representative_party_id, representation_type, eori_context, importer_eori_source,"
                " entry_method, batch_id, content_sha256) values (:i, :t, :m, :v, :sup,"
                " '2027-01-05', :imp, :dec, :rep, :k, 'GB', :src, 'cds', :b, :h)"
            ),
            {
                "i": did,
                "t": tenant,
                "m": mrn,
                "v": version,
                "sup": supersedes,
                "imp": party(s, tenant, importer),
                "dec": party(s, tenant, declarant),
                "rep": party(s, tenant, representative),
                "k": kind,
                "src": source,
                "b": batch,
                "h": hashlib.sha256(f"{mrn}{version}{declarant}{kind}".encode()).hexdigest(),
            },
        )
    return did


def determine(engine: Engine, tenant: UUID, declaration_id: UUID):  # type: ignore[no-untyped-def]
    with tenant_session(engine, tenant_id=tenant) as s:
        return service.determine(
            s, tenant_id=tenant, declaration_id=declaration_id, actor=ACTOR, now=NOW
        )


def count(engine: Engine, tenant: UUID, table: str, where: str = "true") -> int:
    with tenant_session(engine, tenant_id=tenant) as s:
        return int(s.execute(text(f"select count(*) from cbam.{table} where {where}")).scalar_one())


def test_lp_20_with_no_active_rule_the_declaration_waits_for_a_person(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    decl = declaration(app_engine, tenant, batch, "MRN-LP-20", declarant=FORWARDER)
    out = determine(app_engine, tenant, decl)
    assert (out.outcome, out.code, out.liable_party) == ("undetermined", "NO_ACTIVE_RULE", None)
    assert out.created and out.review_task_id is not None
    assert out.as_of_basis == "acceptance_date_provisional"
    # same facts again: no new decision, no second task, the same task is still pointed at
    again = determine(app_engine, tenant, decl)
    assert not again.created and again.decision_id == out.decision_id
    assert again.review_task_id == out.review_task_id
    assert count(app_engine, tenant, "tasks", "type = 'liable_person.review'") == 1
    assert count(app_engine, tenant, "decisions", "rule_id = 'R1-036.liable_person'") == 1


def test_lp_21_a_loaded_but_not_activated_version_is_not_used(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    load(app_engine, FIXTURES / "liable_person_rules" / "fixture.1")  # pending, never activated
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    decl = declaration(app_engine, tenant, batch, "MRN-LP-21", declarant=FORWARDER)
    assert determine(app_engine, tenant, decl).code == "NO_ACTIVE_RULE"


def test_lp_22_freight_forwarder_as_declarant_keeps_the_importer_liable(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """Fixture rows only (invented outcomes): the Phase 3 forwarder exit gate stays open until
    LEGAL-DEC-019 is answered."""
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    decl = declaration(app_engine, tenant, batch, "MRN-LP-22", declarant=FORWARDER, kind="direct")
    out = determine(app_engine, tenant, decl)
    assert (out.outcome, out.liable_party, out.rule_key) == (
        "determined",
        "importer",
        "fixture.forwarder_declarant",
    )
    assert out.source_ids == ["FIXTURE-TEST-SOURCE"] and len(out.dataset_version_ids) == 1
    assert out.review_task_id is None
    with tenant_session(app_engine, tenant_id=tenant) as s:
        imp = s.execute(
            text("select importer_party_id from cbam.declarations where id = :i"), {"i": decl}
        ).scalar_one()
    assert out.liable_party_id == imp


def test_lp_23_direct_importer_and_acting_on_behalf_fixtures(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    direct = declaration(app_engine, tenant, batch, "MRN-LP-23A", declarant=IMPORTER)
    behalf = declaration(
        app_engine, tenant, batch, "MRN-LP-23B", declarant=FORWARDER, kind="direct"
    )
    indirect = declaration(
        app_engine,
        tenant,
        batch,
        "MRN-LP-23C",
        declarant=FORWARDER,
        representative=AGENT,
        kind="indirect",
    )
    assert determine(app_engine, tenant, direct).rule_key == "fixture.direct_importer"
    assert determine(app_engine, tenant, behalf).rule_key == "fixture.forwarder_declarant"
    out = determine(app_engine, tenant, indirect)
    assert out.liable_party == "representative"
    with tenant_session(app_engine, tenant_id=tenant) as s:
        rep = s.execute(
            text("select representative_party_id from cbam.declarations where id = :i"),
            {"i": indirect},
        ).scalar_one()
    assert out.liable_party_id == rep


def test_lp_24_facts_no_rule_covers_are_undetermined_with_a_task(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    decl = declaration(app_engine, tenant, batch, "MRN-LP-24", declarant=FORWARDER, kind="unknown")
    out = determine(app_engine, tenant, decl)
    assert (out.outcome, out.code) == ("undetermined", "NO_MATCHING_RULE")
    assert out.review_task_id is not None


def test_lp_25_loading_rules_later_supersedes_the_undetermined_decision(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    decl = declaration(app_engine, tenant, batch, "MRN-LP-25", declarant=FORWARDER, kind="direct")
    first = determine(app_engine, tenant, decl)
    assert first.outcome == "undetermined"
    fixture_rules_active(app_engine, layout)
    second = determine(app_engine, tenant, decl)
    assert second.outcome == "determined" and second.created
    assert second.decision_id != first.decision_id
    with tenant_session(app_engine, tenant_id=tenant) as s:
        history = service.get_current(s, tenant, decl)
    assert [h["outcome"] for h in history.history] == ["undetermined", "determined"]
    assert history.history[1]["supersedes_id"] == str(first.decision_id)
    assert history.current is not None and history.current.outcome == "determined"


def test_lp_26_only_the_current_declaration_version_can_be_determined(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    v1 = declaration(app_engine, tenant, batch, "MRN-LP-26", declarant=FORWARDER)
    declaration(
        app_engine,
        tenant,
        batch,
        "MRN-LP-26",
        declarant=FORWARDER,
        version=2,
        supersedes=v1,
        kind="direct",
    )
    with pytest.raises(RuleBlockedError):
        determine(app_engine, tenant, v1)


def test_lp_27_another_client_cannot_see_or_determine_a_declaration(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    decl = declaration(app_engine, a, seed_batch(app_engine, store, a), "MRN-LP-27")
    with pytest.raises(TenantMismatchError):
        determine(app_engine, b, decl)
    with tenant_session(app_engine, tenant_id=b) as s, pytest.raises(TenantMismatchError):
        service.get_current(s, b, decl)


def test_lp_28_the_decision_is_audited_without_eoris_and_the_chain_verifies(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    determine(
        app_engine,
        tenant,
        declaration(app_engine, tenant, batch, "MRN-LP-28", declarant=FORWARDER, kind="direct"),
    )
    with tenant_session(app_engine, tenant_id=tenant) as s:
        events = (
            s.execute(
                text(
                    "select after::text from cbam.audit_events"
                    " where action = 'liable_person.determined'"
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1
    assert IMPORTER not in events[0] and FORWARDER not in events[0] and "MRN-LP-28" not in events[0]


def test_lp_29_api_determine_and_read_with_permissions(
    client: TestClient, app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    decl = declaration(
        app_engine,
        tenant,
        seed_batch(app_engine, store, tenant),
        "MRN-LP-29",
        declarant=FORWARDER,
        kind="direct",
    )
    ops = user_for(app_engine, tenant, "operations")
    agent = user_for(app_engine, tenant, "tax_agent")
    path = f"/api/v1/tenants/{tenant}/declarations/{decl}/liable-person"
    assert client.get(path, headers=agent).json() == {"current": None, "history": []}
    assert client.post(path, headers=agent).status_code == 403  # a tax agent cannot trigger it
    posted = client.post(path, headers=ops)
    assert posted.status_code == 200, posted.text
    assert posted.json()["liable_party"] == "importer"
    got = client.get(path, headers=agent).json()
    assert got["current"]["outcome"] == "determined" and len(got["history"]) == 1
    other = make_tenant(app_engine, "B")
    stranger = user_for(app_engine, other, "operations")
    assert client.get(path.replace(str(tenant), str(other)), headers=stranger).status_code == 404


def test_lp_32_r1_036_an_importer_taken_from_the_batch_is_undetermined_end_to_end(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """A file row with no importer EORI falls back to the batch EORI for the ledger, but the
    liable-person engine must not treat that as the importer named on the declaration."""
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    row = good_row(1)
    row[2] = ""
    row[1] = "05/01/2027"
    batch = receive(app_engine, store, tenant, to_csv([row, good_row(2)]))
    assert run(app_engine, store, tenant, batch.id) == "completed"
    with tenant_session(app_engine, tenant_id=tenant) as s:
        found = {
            r.mrn: (r.importer_eori_source, r.eori)
            for r in s.execute(
                text(
                    "select d.mrn, d.importer_eori_source, p.eori from cbam.declarations d"
                    " join cbam.parties p on p.tenant_id = d.tenant_id"
                    " and p.id = d.importer_party_id"
                )
            ).all()
        }
        ids = {r.mrn: r.id for r in s.execute(text("select id, mrn from cbam.declarations")).all()}
    assert found["MRN-SENTINEL-0001"] == ("batch_fallback", IMPORTER)
    assert found["MRN-SENTINEL-0002"] == ("declared", IMPORTER)
    out = determine(app_engine, tenant, ids["MRN-SENTINEL-0001"])
    assert (out.outcome, out.code, out.liable_party) == ("undetermined", "IMPORTER_INFERRED", None)
    assert out.review_task_id is not None


def test_lp_33_r1_036_an_unknown_importer_source_fails_closed(
    app_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    for source in (None, "batch_fallback"):
        decl = declaration(
            app_engine, tenant, batch, f"MRN-LP-33-{source}", declarant=IMPORTER, source=source
        )
        assert determine(app_engine, tenant, decl).code == "IMPORTER_INFERRED"


def test_lp_34_r1_036_a_blank_context_rule_row_does_not_settle_a_declaration(
    app_engine: Engine, admin_engine: Engine, store: InMemoryStore, layout: UUID
) -> None:
    """A loaded row with no eori_context (null) matches nothing, GB or XI."""
    fixture_rules_active(app_engine, layout)
    with admin_engine.begin() as conn:
        conn.execute(text("set local role cbam_owner"))
        conn.execute(text("alter table cbam.ref_liable_person_rules disable trigger user"))
        conn.execute(text("alter table cbam.ref_liable_person_rules no force row level security"))
        conn.execute(text("update cbam.ref_liable_person_rules set eori_context = null"))
        conn.execute(text("alter table cbam.ref_liable_person_rules force row level security"))
        conn.execute(text("alter table cbam.ref_liable_person_rules enable trigger user"))
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)
    decl = declaration(app_engine, tenant, batch, "MRN-LP-34", declarant=IMPORTER)
    out = determine(app_engine, tenant, decl)
    assert (out.outcome, out.code) == ("undetermined", "NO_MATCHING_RULE")


@pytest.mark.parametrize("status", ["draft", "laid"])
def test_lp_35_r1_036_an_active_version_whose_source_is_not_in_force_is_ignored(
    app_engine: Engine, admin_engine: Engine, store: InMemoryStore, layout: UUID, status: str
) -> None:
    """CLAUDE.md rule 2: draft law never drives a decision, even from an ACTIVE dataset."""
    fixture_rules_active(app_engine, layout)
    tenant = make_tenant(app_engine, "A")
    batch = seed_batch(app_engine, store, tenant)  # needs the layout source in force: do it first
    with admin_engine.begin() as conn:
        conn.execute(text("set local role cbam_owner"))
        conn.execute(text("alter table cbam.regulatory_sources disable trigger user"))
        conn.execute(text("alter table cbam.regulatory_sources no force row level security"))
        conn.execute(
            text("update cbam.regulatory_sources set status = :s where source_id = :i"),
            {"s": status, "i": "FIXTURE-TEST-SOURCE"},
        )
        conn.execute(text("alter table cbam.regulatory_sources force row level security"))
        conn.execute(text("alter table cbam.regulatory_sources enable trigger user"))
    decl = declaration(app_engine, tenant, batch, "MRN-LP-35", declarant=IMPORTER)
    out = determine(app_engine, tenant, decl)
    assert (out.outcome, out.code, out.liable_party) == ("undetermined", "NO_ACTIVE_RULE", None)
    assert out.review_task_id is not None

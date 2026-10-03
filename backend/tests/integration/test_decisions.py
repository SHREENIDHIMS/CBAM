"""Decisions: every derived outcome stores rule, versions and an input fingerprint.

CLAUDE.md rule 4: corrections create a new version linked to the old one.
"""

import threading
from datetime import date
from decimal import Decimal
from itertools import pairwise
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from app.core.db import tenant_session
from app.core.decisions import (
    Decision,
    current_decision,
    decision_history,
    fingerprint,
    save_decision,
)
from app.core.ids import uuid7
from tests.integration.conftest import make_tenant

AS_OF = date(2027, 6, 1)
DS = [UUID("00000000-0000-0000-0000-0000000000a1")]


def _decision(outcome: str = "IN_SCOPE", rule_version: str = "1") -> Decision:
    return Decision(
        rule_id="R1-007.scope",
        rule_version=rule_version,
        source_ids=("SRC-1",),
        outcome=outcome,
        reason="commodity code in scope list",
    )


def _save(
    engine: Engine, tenant: UUID, subject: UUID, decision: Decision, **inputs: object
) -> tuple[UUID, bool]:
    with tenant_session(engine, tenant_id=tenant) as s:
        saved = save_decision(
            s,
            tenant_id=tenant,
            subject_type="import_line",
            subject_id=subject,
            decision=decision,
            dataset_version_ids=DS,
            inputs=inputs or {"code": "72081000", "net_mass_kg": Decimal("48200.000000")},
            as_of=AS_OF,
        )
        return saved.id, saved.created


def test_saving_the_same_decision_twice_is_idempotent(app_engine: Engine) -> None:
    t, subject = make_tenant(app_engine), uuid7()
    first, created1 = _save(app_engine, t, subject, _decision())
    second, created2 = _save(app_engine, t, subject, _decision())
    assert created1 is True and created2 is False
    assert first == second
    with tenant_session(app_engine, tenant_id=t) as s:
        assert len(decision_history(s, t, "import_line", subject, "R1-007.scope")) == 1


def test_scale_only_input_change_does_not_create_a_new_decision(app_engine: Engine) -> None:
    t, subject = make_tenant(app_engine), uuid7()
    first, _ = _save(app_engine, t, subject, _decision(), net_mass_kg=Decimal("1.50"))
    second, created = _save(app_engine, t, subject, _decision(), net_mass_kg=Decimal("1.5"))
    assert first == second and created is False


def test_changed_outcome_supersedes_and_keeps_history(app_engine: Engine) -> None:
    t, subject = make_tenant(app_engine), uuid7()
    first, _ = _save(app_engine, t, subject, _decision("IN_SCOPE"))
    second, created = _save(app_engine, t, subject, _decision("OUT_OF_SCOPE"))
    assert created is True and second != first
    with tenant_session(app_engine, tenant_id=t) as s:
        current = current_decision(s, t, "import_line", subject, "R1-007.scope")
        assert current is not None
        assert current.id == second
        assert current.outcome == "OUT_OF_SCOPE"
        assert current.supersedes_id == first
        history = decision_history(s, t, "import_line", subject, "R1-007.scope")
        assert [h.outcome for h in history] == ["IN_SCOPE", "OUT_OF_SCOPE"]


def test_new_rule_version_or_new_input_is_a_new_decision(app_engine: Engine) -> None:
    t, subject = make_tenant(app_engine), uuid7()
    first, _ = _save(app_engine, t, subject, _decision())
    v2, created_v2 = _save(app_engine, t, subject, _decision(rule_version="2"))
    changed, created_in = _save(
        app_engine, t, subject, _decision(rule_version="2"), code="26011100"
    )
    assert created_v2 and created_in
    assert len({first, v2, changed}) == 3


def test_stored_row_carries_traceability(app_engine: Engine) -> None:
    t, subject = make_tenant(app_engine), uuid7()
    _save(app_engine, t, subject, _decision(), code="72081000")
    with tenant_session(app_engine, tenant_id=t) as s:
        row = current_decision(s, t, "import_line", subject, "R1-007.scope")
    assert row is not None
    assert row.rule_version == "1"
    assert row.source_ids == ("SRC-1",)
    assert row.dataset_version_ids == tuple(DS)
    assert row.input_fingerprint == fingerprint({"code": "72081000"})
    assert row.as_of == AS_OF


def test_decisions_cannot_be_edited_or_deleted(app_engine: Engine) -> None:
    t, subject = make_tenant(app_engine), uuid7()
    _save(app_engine, t, subject, _decision())
    for sql in ("update cbam.decisions set outcome = 'X'", "delete from cbam.decisions"):
        with pytest.raises(ProgrammingError), tenant_session(app_engine, tenant_id=t) as s:
            s.execute(text(sql))


def test_decisions_are_tenant_isolated(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    subject = uuid7()
    _save(app_engine, b, subject, _decision())
    with tenant_session(app_engine, tenant_id=a) as s:
        assert s.execute(text("select count(*) from cbam.decisions")).scalar_one() == 0
        assert current_decision(s, a, "import_line", subject, "R1-007.scope") is None


def test_concurrent_conflicting_saves_keep_a_single_current_decision(app_engine: Engine) -> None:
    t, subject = make_tenant(app_engine), uuid7()
    _save(app_engine, t, subject, _decision("IN_SCOPE"))
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def worker(outcome: str) -> None:
        try:
            barrier.wait(timeout=10)
            _save(app_engine, t, subject, _decision(outcome))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"O{i}",)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=20)
    assert errors == []
    with tenant_session(app_engine, tenant_id=t) as s:
        history = decision_history(s, t, "import_line", subject, "R1-007.scope")
        # A strict chain: each row supersedes the one before it, exactly one is current.
        assert len(history) == 5
        for earlier, later in pairwise(history):
            assert later.supersedes_id == earlier.id

# ruff: noqa: F811 - imported pytest fixtures are used as test arguments
"""R1-025 / R1-003 job lease hardening: owner token, back-off release, time-based renewal.

Scenario IDs: IMP-51 only the lease owner renews or releases, IMP-52 a handled failure holds the
lease until the retry is due and does not burn an attempt, IMP-53 renewal while skipping rows.
Product rules, not law. Fixtures are synthetic.
"""

import inspect
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text

from app.core.clock import FrozenClock
from app.core.db import tenant_session
from app.core.storage import InMemoryStore
from app.modules.imports import jobs, processing
from app.modules.imports.processing import ImportJobError, LeaseLostError
from tests.integration.conftest import make_tenant
from tests.integration.test_import_processing import (  # noqa: F401
    NOW,
    Killed,
    at,
    batch_row,
    good_row,
    kill,
    layout,
    limits,
    receive,
    run,
    sweep,
    to_csv,
)


def rows(n: int) -> bytes:
    return to_csv([good_row(i) for i in range(1, n + 1)])


def steal(engine: Engine, tenant: UUID, batch: UUID, token: UUID) -> None:
    with tenant_session(engine, tenant_id=tenant) as s:
        s.execute(
            text("update cbam.import_batches set lease_owner = :t where id = :b"),
            {"t": token, "b": batch},
        )


def test_imp_51_r1_003_a_lease_takeover_writes_a_token_and_a_failure_clears_it(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(4))
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=2, after_chunk=kill)
    held = batch_row(app_engine, tenant, batch.id)
    assert held.lease_owner is not None and held.attempts == 1

    def boom(_rows: int) -> None:
        raise RuntimeError("transient")

    with pytest.raises(ImportJobError):
        run(app_engine, store, tenant, batch.id, clock=at(10), chunk_rows=2, after_chunk=boom)
    released = batch_row(app_engine, tenant, batch.id)
    assert released.lease_owner is None  # handed back by the run that held it
    assert (released.attempts, released.lease_expires_at) == (2, at(10).now())


def test_imp_51_r1_003_a_job_that_lost_its_lease_stops_and_leaves_the_batch_alone(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(6))
    thief = uuid4()

    def takeover(_rows: int) -> None:
        steal(app_engine, tenant, batch.id, thief)  # another worker takes over between chunks

    status = run(app_engine, store, tenant, batch.id, chunk_rows=2, after_chunk=takeover)
    assert status == "validating"  # reported, not raised, and not failed
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.lease_owner, row.rows_total) == (thief, 2)  # no write after the takeover
    assert row.lease_expires_at == NOW + timedelta(seconds=300)  # nor a renewal of its lease


def test_imp_51_r1_003_chunk_renew_and_release_act_only_for_the_token_holder(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(2))
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=1, after_chunk=kill)
    before = batch_row(app_engine, tenant, batch.id)
    stale = processing._Lease()  # a lease token the batch does not hold
    clock = FrozenClock(NOW + timedelta(seconds=50))
    with pytest.raises(LeaseLostError):
        processing._renew(app_engine, clock, tenant, batch.id, stale, 300)
    processing._release_lease(app_engine, clock, tenant, batch.id, stale, 0)
    match = processing.rules.match_layout(("A",), ())
    with pytest.raises(LeaseLostError):
        processing._chunk(
            app_engine, clock, tenant, batch.id, ("A",), match, [(9, ["x"])], stale, 300
        )
    after = batch_row(app_engine, tenant, batch.id)
    assert (after.lease_owner, after.lease_expires_at, after.row_version) == (
        before.lease_owner,
        before.lease_expires_at,
        before.row_version,
    )
    assert after.rows_total == before.rows_total  # the stale chunk wrote nothing


def test_imp_51_r1_003_a_run_that_never_took_the_lease_does_not_release_one(
    app_engine: Engine, layout: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(2))
    calls: list[object] = []
    monkeypatch.setattr(processing, "_release_lease", lambda *a, **k: calls.append(a))

    def broken(*_a: object, **_k: object) -> None:
        raise RuntimeError("database hiccup before the takeover")

    monkeypatch.setattr(processing, "_load_start", broken)
    with pytest.raises(ImportJobError):
        run(app_engine, store, tenant, batch.id)
    assert calls == []


def test_imp_52_r1_003_a_failed_run_holds_the_lease_until_the_retry_is_due(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(6))

    def boom(_rows: int) -> None:
        raise RuntimeError("storage outage")

    with pytest.raises(ImportJobError):
        run(
            app_engine, store, tenant, batch.id,
            chunk_rows=2, after_chunk=boom, release_delay_seconds=60,
        )  # fmt: skip
    row = batch_row(app_engine, tenant, batch.id)
    assert (row.lease_owner, row.lease_expires_at) == (
        None,
        NOW + timedelta(seconds=65),
    )  # back-off plus the 5 s margin
    # the sweeper and an early duplicate leave it alone until the back-off has passed
    assert (tenant, batch.id) not in sweep(app_engine, at(0.5))
    assert run(app_engine, store, tenant, batch.id, clock=at(0.5), chunk_rows=2) == "validating"
    assert batch_row(app_engine, tenant, batch.id).attempts == 1
    # the retry arrives: it takes over, and a handled failure did not burn an attempt
    assert run(app_engine, store, tenant, batch.id, clock=at(1.1), chunk_rows=2) == "completed"
    assert batch_row(app_engine, tenant, batch.id).attempts == 1


def test_imp_52_r1_003_the_task_passes_its_retry_countdown_as_the_release_delay() -> None:
    assert [jobs.retry_countdown(n) for n in range(8)] == [10, 20, 40, 80, 160, 320, 600, 600]
    source = inspect.getsource(jobs.process_batch_task)
    assert "release_delay_seconds=countdown" in source


def test_imp_52_r1_003_a_lost_worker_still_counts_an_attempt_for_the_crash_loop_guard(
    app_engine: Engine, layout: UUID
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(6))
    for minute, attempt in ((0, 1), (10, 2)):
        with pytest.raises(Killed):
            run(
                app_engine,
                store,
                tenant,
                batch.id,
                clock=at(minute),
                chunk_rows=2,
                after_chunk=kill,
            )
        assert batch_row(app_engine, tenant, batch.id).attempts == attempt


class TickClock(FrozenClock):
    """Every reading is `step` seconds after the last: time passes while the job reads."""

    def __init__(self, instant, step: float) -> None:  # type: ignore[no-untyped-def]
        super().__init__(instant)
        self._step = timedelta(seconds=step)

    def now(self):  # type: ignore[no-untyped-def]
        self.advance(self._step)
        return super().now()


def test_imp_53_r1_003_the_lease_is_renewed_on_a_time_basis_while_skipping_saved_rows(
    app_engine: Engine, layout: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(40))
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=20, after_chunk=kill)
    renewals: list[object] = []
    real = processing._renew

    def spy(*a: object, **k: object) -> None:
        renewals.append(a)
        real(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(processing, "_renew", spy)
    short = limits(lease_seconds=30)
    clock = TickClock(NOW + timedelta(minutes=10), step=5)  # the first lease is long expired
    assert run(app_engine, store, tenant, batch.id, clock=clock, chunk_rows=20, limits=short) == (
        "completed"
    )
    # one renewal after the header and layout steps, then one every ~10 seconds over 20 skipped rows
    assert len(renewals) >= 5
    assert batch_row(app_engine, tenant, batch.id).attempts == 2


def test_imp_53_r1_003_a_frozen_clock_does_not_renew_over_and_over(
    app_engine: Engine, layout: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant, store = make_tenant(app_engine, "A"), InMemoryStore()
    batch = receive(app_engine, store, tenant, rows(40))
    with pytest.raises(Killed):
        run(app_engine, store, tenant, batch.id, chunk_rows=20, after_chunk=kill)
    renewals: list[object] = []
    real = processing._renew
    monkeypatch.setattr(
        processing,
        "_renew",
        lambda *a, **k: (renewals.append(a), real(*a, **k))[1],  # type: ignore[arg-type]
    )
    assert run(app_engine, store, tenant, batch.id, clock=at(10), chunk_rows=20) == "completed"
    assert len(renewals) == 1  # only the forced one after the header and layout steps


def test_imp_53_r1_003_the_lease_length_always_comes_from_the_import_limits() -> None:
    default = inspect.signature(processing._chunk).parameters["lease_seconds"].default
    assert default is inspect.Parameter.empty  # no hard-coded 300 any more
    assert "= 300" not in inspect.getsource(processing)

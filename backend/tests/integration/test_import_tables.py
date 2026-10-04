"""R1-003 / CLAUDE.md rules 7, 8, 17: import tables are tenant-isolated, immutable where they
should be, and a batch's status only moves forward (database trigger and application rule)."""

import io
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import tenant_session
from app.core.errors import (
    InvalidRequestError,
    RuleBlockedError,
    StaleVersionError,
    StorageError,
    TenantMismatchError,
)
from app.core.ids import uuid7
from app.core.storage import InMemoryStore
from app.modules.imports import rules, service
from app.modules.imports.schemas import ImportBatchMetadata
from app.modules.imports.service import Actor
from tests.integration.conftest import make_tenant

NOW = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
SYSTEM = Actor("system", None)
CSV = b"mrn,commodity_code\nA1,72011000\n"
META = ImportBatchMetadata(acquisition_method="cds_export", eori="GB123456789012")


def _receive(  # type: ignore[no-untyped-def]
    engine: Engine,
    tenant: UUID,
    data: bytes = CSV,
    store: InMemoryStore | None = None,
    open_session: Callable[[], AbstractContextManager[Session]] | None = None,
):
    store = store or InMemoryStore()
    scanned = service.scan_upload(io.BytesIO(data), max_bytes=10_000)
    return service.receive_file(
        open_session or (lambda: tenant_session(engine, tenant_id=tenant)),
        store=store,
        tenant_id=tenant,
        actor=SYSTEM,
        now=NOW,
        as_of=date(2027, 3, 1),
        file=io.BytesIO(data),
        scanned=scanned,
        filename="a.csv",
        metadata=META,
    )


def _raw(engine: Engine, tenant: UUID | None, sql: str, **params: object) -> int:
    with tenant_session(engine, tenant_id=tenant) as s:
        return s.execute(text(sql), params).rowcount


def _count(engine: Engine, tenant: UUID | None, table: str) -> int:
    with tenant_session(engine, tenant_id=tenant) as s:
        return int(s.execute(text(f"select count(*) from cbam.{table}")).scalar_one())  # noqa: S608


@contextmanager
def _owner(engine: Engine, tenant: UUID) -> Iterator[Session]:
    """Act as the table owner inside one tenant: forced row-level security still applies, but
    the owner's own privileges do not stop the immutability triggers."""
    with tenant_session(engine, tenant_id=tenant) as s:
        s.execute(text("set local role cbam_owner"))
        yield s


TABLES = ("documents", "document_versions", "import_batches")


def test_r1_003_tenant_b_sees_none_of_tenant_as_import_rows(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    _receive(app_engine, a)
    for table in TABLES:
        assert _count(app_engine, a, table) == 1
        assert _count(app_engine, b, table) == 0


def test_r1_003_no_tenant_context_fails_closed_for_reads_and_writes(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    batch = _receive(app_engine, a)
    for table in TABLES:
        assert _count(app_engine, None, table) == 0
    assert (
        _raw(
            app_engine,
            None,
            "update cbam.import_batches set status = 'queued' where id = :i",
            i=batch.id,
        )
        == 0
    )
    with pytest.raises(DBAPIError):
        _raw(
            app_engine,
            None,
            "insert into cbam.documents (id, tenant_id) values (:i, :t)",
            i=uuid7(),
            t=a,
        )


def test_r1_003_tenant_b_cannot_write_or_move_rows_of_tenant_a(app_engine: Engine) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    batch = _receive(app_engine, a)
    with pytest.raises(DBAPIError):
        _raw(
            app_engine,
            b,
            "insert into cbam.documents (id, tenant_id) values (:i, :t)",
            i=uuid7(),
            t=a,
        )
    assert (
        _raw(
            app_engine,
            b,
            "update cbam.import_batches set status = 'queued' where id = :i",
            i=batch.id,
        )
        == 0
    )
    with pytest.raises(DBAPIError):
        _raw(
            app_engine,
            a,
            "update cbam.import_batches set tenant_id = :b where id = :i",
            b=b,
            i=batch.id,
        )


def test_r1_003_app_role_cannot_delete_or_truncate_import_rows(app_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    _receive(app_engine, a)
    for table in TABLES:
        with pytest.raises(DBAPIError):
            _raw(app_engine, a, f"delete from cbam.{table}")  # noqa: S608
        with pytest.raises(DBAPIError):
            _raw(app_engine, a, f"truncate cbam.{table} cascade")


def test_r1_003_documents_and_versions_cannot_be_updated_by_app_or_owner(
    app_engine: Engine, admin_engine: Engine
) -> None:
    a = make_tenant(app_engine, "A")
    _receive(app_engine, a)
    for table, column in (("documents", "created_by"), ("document_versions", "scan_state")):
        value = ":u" if column == "created_by" else "'clean'"
        params = {"u": uuid7()} if column == "created_by" else {}
        with pytest.raises(DBAPIError):  # revoked for cbam_app
            _raw(app_engine, a, f"update cbam.{table} set {column} = {value}", **params)  # noqa: S608
        with pytest.raises(DBAPIError, match="immutable"), _owner(admin_engine, a) as s:
            s.execute(text(f"update cbam.{table} set {column} = {value}"), params)  # noqa: S608
        with pytest.raises(DBAPIError, match="immutable"), _owner(admin_engine, a) as s:
            s.execute(text(f"delete from cbam.{table}"))  # noqa: S608


def test_r1_003_batch_source_facts_are_immutable(app_engine: Engine, admin_engine: Engine) -> None:
    a = make_tenant(app_engine, "A")
    batch = _receive(app_engine, a)
    changes = {
        "filename": "'other.csv'",
        "eori": "'GB999999999999'",
        "file_sha256": f"'{'b' * 64}'",
        "acquisition_method": "'data_request'",
        "cds_report_type": "'export_item'",
        "window_start": "'2020-01-01'",
        "source_owner": "'someone'",
        "acquired_on": "'2027-01-01'",
        "idempotency_key": "'k'",
        "request_fingerprint": "decode(repeat('ab', 32), 'hex')",
        "document_version_id": "null",
        "created_by": f"'{uuid7()}'",
        "created_at": "now()",
    }
    for column, value in changes.items():
        with pytest.raises(DBAPIError, match="immutable"):
            _raw(
                app_engine,
                a,
                f"update cbam.import_batches set {column} = {value} where id = :i",  # noqa: S608
                i=batch.id,
            )
    with pytest.raises(DBAPIError, match="immutable"), _owner(admin_engine, a) as s:
        s.execute(
            text("update cbam.import_batches set filename = 'x' where id = :i"), {"i": batch.id}
        )


def test_r1_003_status_moves_forward_only_and_progress_columns_can_change(
    app_engine: Engine,
) -> None:
    a = make_tenant(app_engine, "A")
    batch = _receive(app_engine, a)
    ok = "update cbam.import_batches set status = :s, rows_total = :n where id = :i"
    assert _raw(app_engine, a, ok, s="parsing", n=10, i=batch.id) == 1
    # Progress alone (same status) is fine.
    assert (
        _raw(
            app_engine,
            a,
            "update cbam.import_batches set rows_processed = 5 where id = :i",
            i=batch.id,
        )
        == 1
    )
    for backward in ("received", "queued"):
        with pytest.raises(DBAPIError, match="cannot move"):
            _raw(
                app_engine,
                a,
                "update cbam.import_batches set status = :s where id = :i",
                s=backward,
                i=batch.id,
            )
    assert (
        _raw(
            app_engine,
            a,
            "update cbam.import_batches set status = 'validating' where id = :i",
            i=batch.id,
        )
        == 1
    )


@pytest.mark.parametrize("terminal", ["completed", "completed_with_errors", "failed", "rejected"])
def test_r1_003_terminal_batches_are_locked(
    app_engine: Engine, admin_engine: Engine, terminal: str
) -> None:
    a = make_tenant(app_engine, "A")
    batch = _receive(app_engine, a)
    assert (
        _raw(
            app_engine,
            a,
            "update cbam.import_batches set status = :s where id = :i",
            s=terminal,
            i=batch.id,
        )
        == 1
    )
    for sql in (
        "update cbam.import_batches set rows_total = 99 where id = :i",
        "update cbam.import_batches set status = 'completed' where id = :i",
        "update cbam.import_batches set status = 'received' where id = :i",
        "update cbam.import_batches set failure_reason = 'x' where id = :i",
    ):
        with pytest.raises(DBAPIError, match="locked"):
            _raw(app_engine, a, sql, i=batch.id)
    with pytest.raises(DBAPIError, match="locked"), _owner(admin_engine, a) as s:
        s.execute(
            text("update cbam.import_batches set rows_total = 1 where id = :i"), {"i": batch.id}
        )


def test_r1_003_checks_reject_bad_rows_even_from_the_owner(
    app_engine: Engine, admin_engine: Engine
) -> None:
    a = make_tenant(app_engine, "A")
    base = {
        "id": uuid7(),
        "t": a,
        "m": "cds_export",
        "f": b"\x00" * 32,
    }
    sql = (
        "insert into cbam.import_batches (id, tenant_id, acquisition_method, request_fingerprint{c}) "
        "values (:id, :t, :m, :f{v})"
    )
    bad = [
        (", eori", ", 'FR123456789012'"),
        (", eori", ", 'GB1234'"),
        (", window_start, window_end", ", '2027-02-01', '2027-01-01'"),
        (", file_sha256", ", repeat('a', 64)"),  # a hash needs a document version
        (", status", ", 'sideways'"),
        (", cds_report_type", ", 'other'"),
    ]
    for cols, vals in bad:
        with pytest.raises(DBAPIError), _owner(admin_engine, a) as s:
            s.execute(text(sql.format(c=cols, v=vals)), {**base, "id": uuid7()})
    with _owner(admin_engine, a) as s:  # manual entry: no file and no hash
        s.execute(
            text(sql.format(c=", eori", v=", 'XI123456789012'")),
            {**base, "m": "manual_entry", "id": uuid7()},
        )
    with pytest.raises(DBAPIError), _owner(admin_engine, a) as s:
        s.execute(
            text(sql.format(c="", v="")), {**base, "m": "manual_entry", "id": uuid7(), "f": b"\x00"}
        )


def test_r1_003_one_batch_per_tenant_and_hash_enforced_by_the_database(
    app_engine: Engine, admin_engine: Engine
) -> None:
    a = make_tenant(app_engine, "A")
    batch = _receive(app_engine, a)
    with (
        pytest.raises(DBAPIError, match="import_batches_tenant_sha"),
        _owner(admin_engine, a) as s,
    ):
        s.execute(
            text(
                "insert into cbam.import_batches (id, tenant_id, file_sha256, document_version_id, "
                "acquisition_method, request_fingerprint) "
                "select :n, tenant_id, file_sha256, document_version_id, acquisition_method, "
                "request_fingerprint from cbam.import_batches where id = :i"
            ),
            {"n": uuid7(), "i": batch.id},
        )


def test_r1_003_concurrent_uploads_of_the_same_file_make_one_batch_and_one_blob(
    app_engine: Engine,
) -> None:
    a = make_tenant(app_engine, "A")
    store = InMemoryStore()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: _receive(app_engine, a, store=store), range(6)))
    assert len({r.id for r in results}) == 1
    assert sum(1 for r in results if not r.replayed) == 1
    assert _count(app_engine, a, "import_batches") == 1
    assert _count(app_engine, a, "documents") == 1
    # Losers delete their own blob: exactly the winner's survives and the database points at it.
    assert len(store.objects) == 1
    with tenant_session(app_engine, tenant_id=a) as s:
        stored = s.execute(text("select storage_key from cbam.document_versions")).scalar_one()
    assert list(store.objects) == [stored]


def test_r1_003_concurrent_uploads_with_different_keys_for_one_file_make_one_batch(
    app_engine: Engine,
) -> None:
    a = make_tenant(app_engine, "A")
    store = InMemoryStore()

    def upload(i: int):  # type: ignore[no-untyped-def]
        scanned = service.scan_upload(io.BytesIO(CSV), max_bytes=10_000)
        return service.receive_file(
            lambda: tenant_session(app_engine, tenant_id=a),
            store=store,
            tenant_id=a,
            actor=SYSTEM,
            now=NOW,
            as_of=date(2027, 3, 1),
            file=io.BytesIO(CSV),
            scanned=scanned,
            filename="a.csv",
            metadata=META,
            idempotency_key=f"key-{i}",
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(upload, range(6)))
    assert len({r.id for r in results}) == 1
    assert sum(1 for r in results if not r.replayed) == 1
    assert _count(app_engine, a, "import_batches") == 1
    assert len(store.objects) == 1


class _StubbornStore(InMemoryStore):
    """A store whose cleanup fails: the request must still succeed."""

    def delete(self, key: str) -> None:
        raise StorageError("deleting the file failed (500)")


@pytest.mark.parametrize("cleanup_works", [True, False])
def test_r1_003_a_request_that_loses_the_race_returns_the_winner_and_discards_its_blob(
    app_engine: Engine, cleanup_works: bool
) -> None:
    a = make_tenant(app_engine, "A")
    winner_store = InMemoryStore()
    loser_store: InMemoryStore = InMemoryStore() if cleanup_works else _StubbornStore()
    calls = {"n": 0}
    winner = {}

    def open_session() -> AbstractContextManager[Session]:
        calls["n"] += 1
        if calls["n"] == 2:  # between the replay pre-check and the insert transaction
            winner["batch"] = _receive(app_engine, a, store=winner_store)
        return tenant_session(app_engine, tenant_id=a)

    result = _receive(app_engine, a, store=loser_store, open_session=open_session)
    assert result.replayed is True
    assert result.id == winner["batch"].id
    assert _count(app_engine, a, "import_batches") == 1
    assert len(winner_store.objects) == 1
    assert len(loser_store.objects) == (0 if cleanup_works else 1)


def test_r1_003_a_failed_transaction_discards_the_stored_blob(
    app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = make_tenant(app_engine, "A")
    store = InMemoryStore()

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(service, "record", boom)
    with pytest.raises(RuntimeError):
        _receive(app_engine, a, store=store)
    assert store.put_calls == 1
    assert store.objects == {}
    assert _count(app_engine, a, "import_batches") == 0
    assert _count(app_engine, a, "documents") == 0


def test_r1_003_the_app_filters_by_tenant_even_when_row_level_security_is_off(
    app_engine: Engine, admin_engine: Engine
) -> None:
    """CLAUDE.md rule 7: the app filter is the second lock. With forced RLS switched off for
    the owner (rolled back at the end), tenant A still cannot see or move tenant B's batch."""
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    batch_b = _receive(app_engine, b)
    batch_a = _receive(app_engine, a, data=CSV + b"A2,72011000\n")
    with admin_engine.connect() as conn:
        outer = conn.begin()
        try:
            conn.execute(text("set local role cbam_owner"))
            conn.execute(text("alter table cbam.import_batches no force row level security"))
            session = Session(conn)
            visible = session.execute(
                text("select count(*) from cbam.import_batches where tenant_id in (:a, :b)"),
                {"a": a, "b": b},
            ).scalar_one()
            assert visible == 2, "row-level security should be off for this check"
            with pytest.raises(TenantMismatchError):
                service.get_batch(session, a, batch_b.id)
            assert service.get_batch(session, a, batch_a.id).id == batch_a.id
            assert [i.id for i in service.list_batches(session, a).items] == [batch_a.id]
            assert [i.id for i in service.list_batches(session, b).items] == [batch_b.id]
            with pytest.raises(TenantMismatchError):
                service.advance_batch(
                    session,
                    tenant_id=a,
                    batch_id=batch_b.id,
                    target="parsing",
                    expected_version=1,
                    actor=SYSTEM,
                    now=NOW,
                )
            fingerprint = rules.request_fingerprint(META.declared())
            assert (
                service._find_replay(
                    session,
                    tenant_id=a,
                    sha256=batch_b.file_sha256 or "",
                    fingerprint=fingerprint,
                    idempotency_key=None,
                )
                is None
            )
        finally:
            outer.rollback()


def test_r1_003_cross_tenant_links_fail_even_for_the_owner(
    app_engine: Engine, admin_engine: Engine
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    _receive(app_engine, b)
    with tenant_session(app_engine, tenant_id=b) as s:
        doc_b = s.execute(text("select id from cbam.documents")).scalar_one()
        version_b = s.execute(text("select id from cbam.document_versions")).scalar_one()
    with pytest.raises(DBAPIError, match="foreign key"), _owner(admin_engine, a) as s:
        s.execute(
            text(
                "insert into cbam.document_versions (id, tenant_id, document_id, version, storage_key, "
                "sha256, size_bytes, mime_detected, original_filename, uploaded_by_type) "
                "values (:i, :t, :d, 2, 'k', repeat('a', 64), 1, 'text/csv', 'x.csv', 'system')"
            ),
            {"i": uuid7(), "t": a, "d": doc_b},
        )
    with pytest.raises(DBAPIError, match="foreign key"), _owner(admin_engine, a) as s:
        s.execute(
            text(
                "insert into cbam.import_batches (id, tenant_id, file_sha256, document_version_id, "
                "acquisition_method, request_fingerprint) "
                "values (:i, :t, repeat('c', 64), :v, 'cds_export', decode(repeat('ab', 32), 'hex'))"
            ),
            {"i": uuid7(), "t": a, "v": version_b},
        )


def test_r1_003_failure_reason_must_be_a_short_code(
    app_engine: Engine,
) -> None:
    a = make_tenant(app_engine, "A")
    batch = _receive(app_engine, a)
    for text_value in ("Bad value 'John Smith' in row 3", "UPPER", "x" * 65, ""):
        with pytest.raises(InvalidRequestError), tenant_session(app_engine, tenant_id=a) as s:
            service.advance_batch(
                s,
                tenant_id=a,
                batch_id=batch.id,
                target="failed",
                expected_version=1,
                actor=SYSTEM,
                now=NOW,
                failure_reason=text_value,
            )
        with pytest.raises(DBAPIError, match="failure_reason"):
            _raw(
                app_engine,
                a,
                "update cbam.import_batches set failure_reason = :r where id = :i",
                r=text_value,
                i=batch.id,
            )
    with tenant_session(app_engine, tenant_id=a) as s:
        audited = s.execute(
            text("select count(*) from cbam.audit_events where reason is not null")
        ).scalar_one()
    assert audited == 0


def test_r1_003_advance_batch_follows_the_rule_writes_audit_and_checks_the_version(
    app_engine: Engine,
) -> None:
    a = make_tenant(app_engine, "A")
    batch = _receive(app_engine, a)
    with tenant_session(app_engine, tenant_id=a) as s:
        moved = service.advance_batch(
            s,
            tenant_id=a,
            batch_id=batch.id,
            target="parsing",
            expected_version=batch.row_version,
            actor=SYSTEM,
            now=NOW,
            progress={"rows_total": 500},
        )
    assert (moved.status, moved.rows_total, moved.row_version) == ("parsing", 500, 2)
    with pytest.raises(StaleVersionError), tenant_session(app_engine, tenant_id=a) as s:
        service.advance_batch(
            s,
            tenant_id=a,
            batch_id=batch.id,
            target="validating",
            expected_version=1,
            actor=SYSTEM,
            now=NOW,
        )
    with pytest.raises(RuleBlockedError) as blocked, tenant_session(app_engine, tenant_id=a) as s:
        service.advance_batch(
            s,
            tenant_id=a,
            batch_id=batch.id,
            target="queued",
            expected_version=2,
            actor=SYSTEM,
            now=NOW,
        )
    assert blocked.value.rule_id == "R1-003.batch_transition"
    with tenant_session(app_engine, tenant_id=a) as s:
        done = service.advance_batch(
            s,
            tenant_id=a,
            batch_id=batch.id,
            target="failed",
            expected_version=2,
            actor=SYSTEM,
            now=NOW,
            failure_reason="not_a_cds_report",
        )
    assert done.failure_reason == "not_a_cds_report"
    with pytest.raises(RuleBlockedError), tenant_session(app_engine, tenant_id=a) as s:
        service.advance_batch(
            s,
            tenant_id=a,
            batch_id=batch.id,
            target="completed",
            expected_version=3,
            actor=SYSTEM,
            now=NOW,
        )
    with tenant_session(app_engine, tenant_id=a) as s:
        actions = (
            s.execute(
                text(
                    "select action from cbam.audit_events where object_id = :i order by chain_seq"
                ),
                {"i": batch.id},
            )
            .scalars()
            .all()
        )
    assert actions == [
        "import_batch.created",
        "import_batch.status_changed",
        "import_batch.status_changed",
    ]

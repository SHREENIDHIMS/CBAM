"""R1-003: the same source file can be replayed without duplicate business records.

Scenario IDs: IMP-01 replay, IMP-02 conflicting details, IMP-03 refused content and size.
Product rules, not law: no regulatory source applies. Fixtures are synthetic CSV text.
"""

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.audit import verify_chain
from app.core.clock import FrozenClock, get_clock
from app.core.config import Settings, get_settings
from app.core.db import tenant_session
from app.core.errors import PayloadTooLargeError
from app.core.storage import InMemoryStore, get_object_store
from app.core.tenancy import get_engine_dep, get_verifier
from app.main import create_app
from app.modules.imports import service
from app.modules.imports.api import _capped
from tests.helpers_auth import bearer, verifier
from tests.integration.conftest import make_member, make_tenant, make_user

NOW = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
CSV = b"mrn,commodity_code,net_mass_kg\n27GB0000000000001,72011000,1000.5\n"
META = {
    "acquisition_method": "get_customs_data",
    "cds_report_type": "import_item",
    "eori": "GB123456789012",
    "window_start": "2027-01-01",
    "window_end": "2027-01-31",
    "source_owner": "client",
    "acquired_on": "2027-02-02",
}
MAX_BYTES = 4000


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def client(app_engine: Engine, store: InMemoryStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine
    app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)
    app.dependency_overrides[get_object_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: Settings(import_max_file_bytes=MAX_BYTES)
    with TestClient(app) as c:
        yield c


def _user(engine: Engine, tenant: UUID, role: str = "operations") -> UUID:
    user = make_user(engine)
    make_member(engine, tenant, user, role)
    return user


def _h(user: UUID, **extra: str) -> dict[str, str]:
    return {**bearer(user, aal="aal2"), **extra}


def _url(tenant: UUID, batch: object | None = None) -> str:
    base = f"/api/v1/tenants/{tenant}/import-batches"
    return f"{base}/{batch}" if batch else base


def _upload(
    client: TestClient,
    tenant: UUID,
    user: UUID,
    data: bytes = CSV,
    meta: dict[str, str] | None = None,
    name: str = "report.csv",
    **headers: str,
):  # type: ignore[no-untyped-def]
    return client.post(
        _url(tenant),
        files={"file": (name, data, "text/csv")},
        data=META if meta is None else meta,
        headers=_h(user, **headers),
    )


def _count(engine: Engine, tenant: UUID, table: str) -> int:
    with tenant_session(engine, tenant_id=tenant) as s:
        return int(s.execute(text(f"select count(*) from cbam.{table}")).scalar_one())  # noqa: S608


def test_imp_01_r1_003_new_file_is_accepted_and_stored_with_its_hash(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    r = _upload(client, t, user)
    assert r.status_code == 202, r.text
    body = r.json()
    sha = hashlib.sha256(CSV).hexdigest()
    assert body["replayed"] is False
    assert body["status"] == "received"
    assert body["file_sha256"] == sha
    assert body["filename"] == "report.csv"
    assert body["acquisition_method"] == "get_customs_data"
    assert body["cds_report_type"] == "import_item"
    assert body["eori"] == "GB123456789012"
    assert body["window_start"] == "2027-01-01"
    assert body["acquired_on"] == "2027-02-02"
    assert body["created_by"] == str(user)
    assert body["rows_total"] == 0
    assert r.headers["etag"] == '"1"'
    assert r.headers["location"].endswith(f"/import-batches/{body['id']}")
    assert list(store.objects.values()) == [CSV]
    (stored_key,) = store.objects
    assert stored_key.startswith(f"tenants/{t}/")
    assert sha not in stored_key  # random key: nothing about the content is in it
    with tenant_session(app_engine, tenant_id=t) as s:
        row = s.execute(text("select storage_key, sha256 from cbam.document_versions")).one()
    assert (row.storage_key, row.sha256) == (stored_key, sha)
    assert _count(app_engine, t, "documents") == 1
    assert _count(app_engine, t, "document_versions") == 1


def test_imp_01_r1_003_same_file_twice_gives_one_batch_and_a_replay(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    first = _upload(client, t, user)
    second = _upload(client, t, user, name="renamed-copy.csv")
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["id"] == first.json()["id"]
    assert _count(app_engine, t, "import_batches") == 1
    assert _count(app_engine, t, "documents") == 1
    assert _count(app_engine, t, "document_versions") == 1
    assert store.put_calls == 1
    # The original filename of the first upload is kept (source facts are never overwritten).
    assert second.json()["filename"] == "report.csv"
    # A replay is not a state change: one audit event only.
    with tenant_session(app_engine, tenant_id=t) as s:
        actions = s.execute(text("select action from cbam.audit_events")).scalars().all()
    assert actions.count("import_batch.created") == 1


def test_imp_01_r1_003_the_same_bytes_in_another_tenant_are_a_separate_batch(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    ua, ub = _user(app_engine, a), _user(app_engine, b)
    ra, rb = _upload(client, a, ua), _upload(client, b, ub)
    assert (ra.status_code, rb.status_code) == (202, 202)
    assert ra.json()["id"] != rb.json()["id"]
    assert len(store.objects) == 2
    assert sorted(k.split("/")[1] for k in store.objects) == sorted([str(a), str(b)])


def test_imp_01_r1_003_idempotency_key_replays_the_same_request(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    first = _upload(client, t, user, **{"Idempotency-Key": "abc-123"})
    again = _upload(client, t, user, **{"Idempotency-Key": "abc-123"})
    assert (first.status_code, again.status_code) == (202, 200)
    assert again.json()["id"] == first.json()["id"]
    assert _count(app_engine, t, "import_batches") == 1


def test_imp_02_r1_003_idempotency_key_reused_for_another_file_is_409(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    assert _upload(client, t, user, **{"Idempotency-Key": "k1"}).status_code == 202
    other = _upload(client, t, user, data=CSV + b"A2,72011000,1\n", **{"Idempotency-Key": "k1"})
    assert other.status_code == 409
    assert other.headers["content-type"].startswith("application/problem+json")
    assert _count(app_engine, t, "import_batches") == 1


def test_imp_02_r1_003_same_bytes_with_different_declared_details_is_409(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    first = _upload(client, t, user)
    clash = _upload(client, t, user, meta={**META, "window_end": "2027-02-28"})
    assert clash.status_code == 409
    assert clash.headers["content-type"].startswith("application/problem+json")
    assert str(first.json()["id"]) in clash.json()["detail"]
    assert _count(app_engine, t, "import_batches") == 1
    assert store.put_calls == 1
    # Different EORI is also a different declaration.
    assert _upload(client, t, user, meta={**META, "eori": "XI123456789012"}).status_code == 409


@pytest.mark.parametrize(
    "data",
    [
        b"PK\x03\x04\x14\x00\x06\x00\x08\x00" + b"\x00" * 50,  # xlsx / zip
        b"%PDF-1.7\n1 0 obj\x00\x01\n",
        b"mrn,desc\nA1,ok\n\x00\x00\x00\n",  # NUL byte after a plausible start
        b"mrn,desc\nA1,\xff\xfe broken utf-8\n",
        "mrn,desc\nA1,é".encode()[:-1],  # a cut-off multi-byte character
    ],
)
def test_imp_03_r1_003_binary_or_non_utf8_content_is_refused_before_storing(
    client: TestClient, app_engine: Engine, store: InMemoryStore, data: bytes
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    r = _upload(client, t, user, data=data, name="renamed.csv")
    assert r.status_code == 415, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert store.objects == {}
    assert _count(app_engine, t, "import_batches") == 0
    assert _count(app_engine, t, "documents") == 0


def test_imp_03_r1_003_empty_or_headerless_files_are_422(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    assert _upload(client, t, user, data=b"").status_code == 422
    assert _upload(client, t, user, data=b"just some words\nand more words\n").status_code == 422
    assert store.objects == {}


def test_imp_03_r1_003_oversize_file_is_413_problem_json(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    big = b"a,b\n" + b"1,2\n" * (MAX_BYTES // 4)  # just over the limit: caught while hashing
    r = _upload(client, t, user, data=big)
    assert r.status_code == 413, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    huge = b"a,b\n" + b"1,2\n" * 50_000  # far over: refused from the Content-Length header
    assert _upload(client, t, user, data=huge).status_code == 413
    assert store.objects == {}
    assert _count(app_engine, t, "import_batches") == 0
    exact = b"a,b\n" + b"x" * (MAX_BYTES - 4)
    assert len(exact) == MAX_BYTES
    assert _upload(client, t, user, data=exact).status_code == 202


def test_r1_003_request_body_is_cut_off_without_a_content_length() -> None:
    async def body():  # type: ignore[no-untyped-def]
        for _ in range(10):
            yield b"x" * 1000

    async def drain() -> int:
        total = 0
        async for chunk in _capped(body(), 2500):
            total += len(chunk)
        return total

    with pytest.raises(PayloadTooLargeError):
        asyncio.run(drain())


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"acquisition_method": "manual_entry"}, "acquisition_method"),
        ({"acquisition_method": "carrier_pigeon"}, "acquisition_method"),
        ({"cds_report_type": "everything"}, "cds_report_type"),
        ({"eori": "FR123456789012"}, "eori"),
        ({"eori": "GB12345"}, "eori"),
        ({"window_start": "2027-02-01", "window_end": "2027-01-01"}, "window_end"),
        ({"window_start": "", "window_end": "2027-01-31"}, "window_end"),
        ({"window_start": "not-a-date"}, "window_start"),
    ],
)
def test_r1_003_declared_details_are_validated(
    client: TestClient,
    app_engine: Engine,
    store: InMemoryStore,
    override: dict[str, str],
    field: str,
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    r = _upload(client, t, user, meta={**META, **override})
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert store.objects == {}
    assert any(field in e["loc"] or field in e["msg"] for e in r.json()["errors"])


def test_r1_003_future_acquisition_date_and_missing_file_are_422(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    assert _upload(client, t, user, meta={**META, "acquired_on": "2027-03-02"}).status_code == 422
    r = client.post(_url(t), data=META, files={"other": ("x.csv", CSV)}, headers=_h(user))
    assert r.status_code == 422
    r = client.post(_url(t), json=META, headers=_h(user))
    assert r.status_code == 415


def test_r1_003_only_the_method_is_required_and_filenames_are_sanitised(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    r = _upload(
        client, t, user, meta={"acquisition_method": "manual_upload"}, name="..\\..\\evil/x.csv"
    )
    assert r.status_code == 202, r.text
    assert r.json()["filename"] == "x.csv"
    assert r.json()["eori"] is None
    assert all("evil" not in key for key in store.objects)


def test_r1_003_audit_event_is_written_with_no_filename_or_file_content(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    batch = _upload(client, t, user, name="clients-secret-name.csv").json()
    with tenant_session(app_engine, tenant_id=t) as s:
        row = s.execute(
            text(
                "select actor_type, actor_id, object_type, object_id, after::text as after, "
                "before from cbam.audit_events where action = 'import_batch.created'"
            )
        ).one()
        assert verify_chain(s, t).ok
    assert (row.actor_type, row.actor_id, row.object_type) == ("user", user, "import_batch")
    assert str(row.object_id) == batch["id"]
    assert row.before is None
    assert batch["file_sha256"] in row.after
    assert "clients-secret-name" not in row.after
    assert "mrn" not in row.after


def test_r1_003_get_and_list_import_batches_with_cursor_paging(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    ids = []
    for i in range(5):
        r = _upload(client, t, user, data=CSV + f"A{i},72011000,{i}\n".encode())
        ids.append(r.json()["id"])
    one = client.get(_url(t, ids[0]), headers=_h(user))
    assert one.status_code == 200
    assert one.headers["etag"] == '"1"'
    assert one.json()["id"] == ids[0]
    assert "replayed" not in one.json()
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get(_url(t), params=params, headers=_h(user)).json()
        seen += [i["id"] for i in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert seen == list(reversed(ids))  # newest first, no gaps, no repeats
    queued = client.get(_url(t), params={"status": "queued"}, headers=_h(user)).json()
    assert queued["items"] == []
    bad = client.get(_url(t), params={"cursor": "not-a-cursor"}, headers=_h(user))
    assert bad.status_code == 422


def test_r1_003_another_tenants_batch_is_404_and_foreign_tenant_paths_are_404(
    client: TestClient, app_engine: Engine
) -> None:
    a, b = make_tenant(app_engine, "A"), make_tenant(app_engine, "B")
    ua, ub = _user(app_engine, a), _user(app_engine, b)
    batch_a = _upload(client, a, ua).json()["id"]
    # B's own route, A's batch id.
    r = client.get(_url(b, batch_a), headers=_h(ub))
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert client.get(_url(b), headers=_h(ub)).json()["items"] == []
    # A's route as B's user: not a member, so the tenant looks absent.
    assert client.get(_url(a, batch_a), headers=_h(ub)).status_code == 404
    assert client.get(_url(a), headers=_h(ub)).status_code == 404
    assert _upload(client, a, ub).status_code == 404


@pytest.mark.parametrize(
    ("role", "can_write", "can_read"),
    [
        ("operations", True, True),
        ("client_admin", True, True),
        ("reviewer", False, True),
        ("approver", False, True),
        ("tax_agent", False, True),
        ("domain_owner", False, False),
        ("supplier", False, False),
    ],
)
def test_r1_003_permissions_imports_write_and_read(
    client: TestClient, app_engine: Engine, role: str, can_write: bool, can_read: bool
) -> None:
    t = make_tenant(app_engine)
    owner = _user(app_engine, t)
    batch = _upload(client, t, owner).json()["id"]
    user = _user(app_engine, t, role)
    write = _upload(client, t, user, data=CSV + b"A9,1,1\n")
    assert write.status_code == (202 if can_write else 403), write.text
    assert client.get(_url(t), headers=_h(user)).status_code == (200 if can_read else 403)
    assert client.get(_url(t, batch), headers=_h(user)).status_code == (200 if can_read else 403)
    if not can_write:
        assert write.headers["content-type"].startswith("application/problem+json")


def test_r1_003_no_token_is_401_and_nothing_is_stored(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    r = client.post(_url(t), files={"file": ("a.csv", CSV)}, data=META)
    assert r.status_code == 401
    assert store.objects == {}


def test_r1_003_unconfigured_storage_is_503_problem_json(app_engine: Engine) -> None:
    app = create_app()
    app.dependency_overrides[get_verifier] = verifier
    app.dependency_overrides[get_engine_dep] = lambda: app_engine
    app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)
    app.dependency_overrides[get_settings] = lambda: Settings(supabase_url="")
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    with TestClient(app) as c:
        r = _upload(c, t, user)
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert _count(app_engine, t, "import_batches") == 0


def _move_batch(engine: Engine, tenant: UUID, batch_id: str, status: str) -> None:
    with tenant_session(engine, tenant_id=tenant) as s:
        s.execute(
            text("update cbam.import_batches set status = :s where id = :i"),
            {"s": status, "i": UUID(batch_id)},
        )


@pytest.mark.parametrize("status", ["failed", "rejected"])
def test_imp_04_r1_003_the_same_bytes_after_a_failed_or_rejected_batch_make_a_new_batch(
    client: TestClient, app_engine: Engine, store: InMemoryStore, status: str
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    old = _upload(client, t, user, **{"Idempotency-Key": "same-key"}).json()
    _move_batch(app_engine, t, old["id"], status)
    again = _upload(client, t, user, **{"Idempotency-Key": "same-key"})
    assert again.status_code == 202, again.text
    assert again.json()["replayed"] is False
    assert again.json()["id"] != old["id"]
    assert again.json()["document_version_id"] != old["document_version_id"]
    assert _count(app_engine, t, "import_batches") == 2
    assert len(store.objects) == 2
    # The old batch stays as history, untouched.
    assert client.get(_url(t, old["id"]), headers=_h(user)).json()["status"] == status
    # And the new, live batch replays as usual.
    third = _upload(client, t, user)
    assert (third.status_code, third.json()["id"]) == (200, again.json()["id"])


@pytest.mark.parametrize("status", ["completed", "completed_with_errors"])
def test_imp_04_r1_003_the_same_bytes_after_a_completed_batch_is_a_replay(
    client: TestClient, app_engine: Engine, status: str
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    old = _upload(client, t, user).json()
    _move_batch(app_engine, t, old["id"], status)
    again = _upload(client, t, user)
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["id"] == old["id"]
    assert _count(app_engine, t, "import_batches") == 1


def test_imp_05_r1_003_a_different_idempotency_key_for_a_known_file_replays_and_ignores_the_key(
    client: TestClient, app_engine: Engine
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    first = _upload(client, t, user, **{"Idempotency-Key": "first"})
    second = _upload(client, t, user, **{"Idempotency-Key": "second"})
    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json()["id"] == first.json()["id"]
    with tenant_session(app_engine, tenant_id=t) as s:
        keys = s.execute(text("select idempotency_key from cbam.import_batches")).scalars().all()
    assert keys == ["first"]


@pytest.mark.parametrize("bad", ["", "has space", "tab\there", "x" * 201, "caf\u00e9"])
def test_imp_06_r1_003_a_bad_idempotency_key_header_is_422(
    client: TestClient, app_engine: Engine, store: InMemoryStore, bad: str
) -> None:
    t = make_tenant(app_engine)
    user = _user(app_engine, t)
    try:
        r = _upload(client, t, user, **{"Idempotency-Key": bad})
    except UnicodeEncodeError:  # a non-ASCII header cannot even be sent
        return
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert store.objects == {}
    assert _count(app_engine, t, "import_batches") == 0


def test_imp_07_r1_003_concurrent_uploads_per_tenant_are_capped_with_429(
    client: TestClient, app_engine: Engine, store: InMemoryStore
) -> None:
    t = make_tenant(app_engine)
    other = make_tenant(app_engine, "Other")
    user, other_user = _user(app_engine, t), _user(app_engine, other)
    client.app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[attr-defined]
        import_max_file_bytes=MAX_BYTES, import_max_concurrent_uploads_per_tenant=2
    )
    service.upload_limiter.acquire(t, 2)
    service.upload_limiter.acquire(t, 2)
    try:
        r = _upload(client, t, user)
        assert r.status_code == 429, r.text
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.headers["retry-after"] == "5"
        assert store.objects == {}
        # Another client is not affected.
        assert _upload(client, other, other_user).status_code == 202
    finally:
        service.upload_limiter.release(t)
        service.upload_limiter.release(t)
    assert service.upload_limiter.active(t) == 0
    assert _upload(client, t, user).status_code == 202
    assert service.upload_limiter.active(t) == 0  # released after success and after errors
    assert _upload(client, t, user, data=b"\x00bin").status_code == 415
    assert service.upload_limiter.active(t) == 0

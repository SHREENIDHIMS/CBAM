"""Object storage for R1-003: random tenant-prefixed keys, Supabase REST calls, and the
service-role key never reaching an error, a repr or a Sentry event (security finding H1)."""

import io
import json
from collections.abc import Callable
from uuid import UUID

import httpx
import pytest
import sentry_sdk
from pydantic import SecretStr
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app.core.config import Settings
from app.core.errors import NotConfiguredError, StorageError
from app.core.observability import init_sentry
from app.core.storage import InMemoryStore, SupabaseStorage, get_object_store, new_object_key

URL = "http://127.0.0.1:54321"
KEY = "service-role-secret-sentinel-4f9c1a"
TENANT = UUID("11111111-1111-1111-1111-111111111111")


def _store(handler) -> SupabaseStorage:  # type: ignore[no-untyped-def]
    return SupabaseStorage(
        URL, SecretStr(KEY), "customs-imports", transport=httpx.MockTransport(handler)
    )


def test_r1_003_keys_are_random_and_tenant_prefixed_not_content_derived() -> None:
    a, b = new_object_key(TENANT), new_object_key(TENANT)
    assert a != b
    assert a.startswith(f"tenants/{TENANT}/")
    assert len(a.split("/")) == 3
    UUID(a.rsplit("/", 1)[1])


def test_r1_003_in_memory_store_round_trips_deletes_and_never_overwrites() -> None:
    store = InMemoryStore()
    store.put("k", io.BytesIO(b"abc"), size=3, content_type="text/csv")
    with store.open("k") as f:
        assert f.read() == b"abc"
    with pytest.raises(StorageError):
        store.put("k", io.BytesIO(b"abc"), size=3, content_type="text/csv")
    with pytest.raises(StorageError):
        store.put("k2", io.BytesIO(b"abc"), size=4, content_type="text/csv")
    store.delete("k")
    store.delete("k")  # a missing object is fine
    with pytest.raises(StorageError):
        store.open("k")


def test_r1_003_put_posts_bytes_to_the_private_bucket_with_the_client_credentials() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["apikey"] = request.headers["apikey"]
        seen["upsert"] = request.headers["x-upsert"]
        seen["length"] = request.headers["content-length"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"Key": "customs-imports/x"})

    key = new_object_key(TENANT)
    _store(handler).put(key, io.BytesIO(b"a,b\n1,2\n"), size=8, content_type="text/csv")
    assert seen["method"] == "POST"
    assert seen["url"] == f"{URL}/storage/v1/object/customs-imports/{key}"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["apikey"] == KEY
    assert seen["upsert"] == "false"
    assert seen["length"] == "8"
    assert seen["body"] == b"a,b\n1,2\n"


def test_r1_003_an_existing_key_is_an_error_not_a_silent_success() -> None:
    with pytest.raises(StorageError):
        _store(lambda _r: httpx.Response(409, json={"error": "Duplicate"})).put(
            "k", io.BytesIO(b"x"), size=1, content_type="text/csv"
        )


def test_r1_003_delete_removes_the_object_and_tolerates_a_missing_one() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(404 if len(seen) == 2 else 200, json={})

    store = _store(handler)
    store.delete("tenants/t/k")
    store.delete("tenants/t/k")
    assert seen == [("DELETE", "/storage/v1/object/customs-imports/tenants/t/k")] * 2
    with pytest.raises(StorageError):
        _store(lambda _r: httpx.Response(500)).delete("k")


def _failing_stores() -> list[SupabaseStorage]:
    def os_error(request: httpx.Request) -> httpx.Response:
        raise OSError(f"disk exploded while sending {KEY} to {request.url}")

    def stream_error(request: httpx.Request) -> httpx.Response:
        raise httpx.StreamError(f"stream broke, header was Bearer {KEY}")

    def connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} with {KEY}")

    def invalid_url(_r: httpx.Request) -> httpx.Response:
        raise httpx.InvalidURL(f"bad url {KEY}")

    def value_error(_r: httpx.Request) -> httpx.Response:
        raise ValueError(f"unexpected {KEY}")

    def server_error(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"boom {KEY} secret-file-contents")

    return [
        _store(h)
        for h in (os_error, stream_error, connect_error, invalid_url, value_error, server_error)
    ]


def _operations(store: SupabaseStorage) -> list[Callable[[], object]]:
    return [
        lambda: store.put("k", io.BytesIO(b"x"), size=1, content_type="text/csv"),
        lambda: store.open("k"),
        lambda: store.delete("k"),
        lambda: store.signed_url("k", expires_in=60),
    ]


def test_r1_003_every_failure_becomes_a_storage_error_without_the_key() -> None:
    for store in _failing_stores():
        for operation in _operations(store):
            with pytest.raises(StorageError) as exc:
                operation()
            error = exc.value
            assert KEY not in str(error)
            assert KEY not in repr(error)
            assert "secret-file-contents" not in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None or error.__suppress_context__ is True
        assert KEY not in repr(store)


class _CapturingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.payloads: list[bytes] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.payloads.append(envelope.serialize())


@pytest.mark.parametrize("failure", ["os_error", "stream_error"])
def test_r1_003_the_service_key_never_reaches_a_sentry_event(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "os_error":
            raise OSError(f"disk exploded {KEY}")
        raise httpx.StreamError(f"stream broke {KEY}")

    transport = _CapturingTransport()
    assert init_sentry("http://public@127.0.0.1:1/1", "test", transport=transport)
    try:
        store = _store(handler)
        service_key = KEY  # a local that Sentry would capture if local variables were on
        assert service_key
        try:
            store.put("k", io.BytesIO(b"x"), size=1, content_type="text/csv")
        except StorageError as exc:
            sentry_sdk.capture_exception(exc)
        sentry_sdk.flush()
    finally:
        sentry_sdk.get_client().close()
    assert transport.payloads, "the event was not captured, so the test proves nothing"
    for payload in transport.payloads:
        assert KEY.encode() not in payload
        assert b"storing the file failed" in payload
        assert b'"vars"' not in payload  # local variables are not attached at all


def test_r1_003_signed_url_is_built_from_the_signing_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"expiresIn": 300}
        return httpx.Response(200, json={"signedURL": "/object/sign/customs-imports/k?token=t"})

    url = _store(handler).signed_url("k", expires_in=300)
    assert url == f"{URL}/storage/v1/object/sign/customs-imports/k?token=t"
    with pytest.raises(StorageError):
        _store(lambda _r: httpx.Response(200, json={})).signed_url("k", expires_in=300)


def test_r1_003_signed_url_lifetime_setting_is_capped_at_five_minutes() -> None:
    assert Settings().signed_url_ttl_seconds == 300
    for bad in (0, 301):
        with pytest.raises(ValueError):
            Settings(signed_url_ttl_seconds=bad)


def test_r1_003_unconfigured_storage_is_a_503_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(NotConfiguredError):
            get_object_store()
    finally:
        get_settings.cache_clear()

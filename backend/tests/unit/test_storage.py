"""Object storage: content-addressed keys, Supabase REST calls, no secret in errors (R1-003)."""

import io
import json
from uuid import UUID

import httpx
import pytest

from app.core.errors import NotConfiguredError, StorageError
from app.core.storage import InMemoryStore, SupabaseStorage, content_key, get_object_store

URL = "http://127.0.0.1:54321"
KEY = "service-role-secret-value"
TENANT = UUID("11111111-1111-1111-1111-111111111111")
SHA = "a" * 64


def _store(handler) -> SupabaseStorage:  # type: ignore[no-untyped-def]
    return SupabaseStorage(URL, KEY, "customs-imports", transport=httpx.MockTransport(handler))


def test_key_is_tenant_then_sha256_and_rejects_anything_else() -> None:
    assert content_key(TENANT, SHA) == f"{TENANT}/{SHA}"
    for bad in ("../x", "A" * 64, "a" * 63, ""):
        with pytest.raises(ValueError):
            content_key(TENANT, bad)


def test_in_memory_store_round_trips_and_checks_size() -> None:
    store = InMemoryStore()
    store.put("k", io.BytesIO(b"abc"), size=3, content_type="text/csv")
    with store.open("k") as f:
        assert f.read() == b"abc"
    with pytest.raises(StorageError):
        store.put("k2", io.BytesIO(b"abc"), size=4, content_type="text/csv")
    with pytest.raises(StorageError):
        store.open("missing")


def test_put_posts_bytes_to_the_private_bucket_with_the_service_key() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["upsert"] = request.headers["x-upsert"]
        seen["length"] = request.headers["content-length"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"Key": "customs-imports/x"})

    _store(handler).put(
        f"{TENANT}/{SHA}", io.BytesIO(b"a,b\n1,2\n"), size=8, content_type="text/csv"
    )
    assert seen["method"] == "POST"
    assert seen["url"] == f"{URL}/storage/v1/object/customs-imports/{TENANT}/{SHA}"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["upsert"] == "false"  # never overwrite
    assert seen["length"] == "8"
    assert seen["body"] == b"a,b\n1,2\n"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(409, json={"error": "Duplicate"}),
        httpx.Response(400, json={"error": "Duplicate", "statusCode": "409"}),
    ],
)
def test_put_of_an_existing_key_is_fine_because_keys_are_content_addressed(
    response: httpx.Response,
) -> None:
    _store(lambda _r: response).put("k", io.BytesIO(b"x"), size=1, content_type="text/csv")


def test_put_failure_never_leaks_the_key_or_file_contents() -> None:
    def server_error(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"boom {KEY} secret-file-contents")

    with pytest.raises(StorageError) as exc:
        _store(server_error).put("k", io.BytesIO(b"x"), size=1, content_type="text/csv")
    assert KEY not in str(exc.value)
    assert "secret-file-contents" not in str(exc.value)
    assert "500" in str(exc.value)

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} with {KEY}")

    with pytest.raises(StorageError) as exc2:
        _store(unreachable).put("k", io.BytesIO(b"x"), size=1, content_type="text/csv")
    assert KEY not in str(exc2.value)
    assert "ConnectError" in str(exc2.value)


def test_open_streams_the_object_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            request.url.path == f"/storage/v1/object/authenticated/customs-imports/{TENANT}/{SHA}"
        )
        return httpx.Response(200, content=b"a,b\n1,2\n")

    with _store(handler).open(f"{TENANT}/{SHA}") as f:
        assert f.read() == b"a,b\n1,2\n"
    with pytest.raises(StorageError):
        _store(lambda _r: httpx.Response(404, json={"error": "not_found"})).open("k")


def test_signed_url_is_built_from_the_signing_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"expiresIn": 300}
        return httpx.Response(200, json={"signedURL": "/object/sign/customs-imports/k?token=t"})

    url = _store(handler).signed_url("k", expires_in=300)
    assert url == f"{URL}/storage/v1/object/sign/customs-imports/k?token=t"
    with pytest.raises(StorageError):
        _store(lambda _r: httpx.Response(200, json={})).signed_url("k", expires_in=300)


def test_unconfigured_storage_is_a_503_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(NotConfiguredError):
            get_object_store()
    finally:
        get_settings.cache_clear()

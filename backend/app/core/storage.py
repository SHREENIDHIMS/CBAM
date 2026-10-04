"""Object storage for original files (R1-003, R1-048). Backend only.

Files live in private Supabase Storage buckets, content-addressed as `{tenant_id}/{sha256}`.
The service-role key is used here only and never reaches a log, an error or the frontend
(CLAUDE.md section 9, rule 18). Callers get time-limited signed URLs, issued by the API.
"""

import re
import tempfile
from collections.abc import Iterator
from functools import lru_cache
from typing import BinaryIO, Protocol, cast
from urllib.parse import quote
from uuid import UUID

import httpx

from app.core.config import get_settings
from app.core.errors import NotConfiguredError, StorageError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 64 * 1024


def content_key(tenant_id: UUID, sha256: str) -> str:
    """The storage key for a file: tenant first, so keys can never collide across tenants."""
    if not _SHA256.match(sha256):
        raise ValueError("sha256 must be 64 lowercase hex characters")
    return f"{tenant_id}/{sha256}"


class ObjectStore(Protocol):
    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None:
        """Store the bytes under `key`. Storing the same key again is not an error: keys are
        content-addressed, so the bytes are the same."""
        ...

    def open(self, key: str) -> BinaryIO:
        """The stored bytes, as a seekable binary file. The caller closes it."""
        ...

    def signed_url(self, key: str, *, expires_in: int) -> str:
        """A time-limited download URL."""
        ...


class InMemoryStore:
    """For tests: nothing leaves the process."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0

    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None:
        self.put_calls += 1
        body = data.read()
        if len(body) != size:
            raise StorageError("the size does not match the data")
        self.objects[key] = body

    def open(self, key: str) -> BinaryIO:
        if key not in self.objects:
            raise StorageError("the object does not exist")
        spooled = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        spooled.write(self.objects[key])
        spooled.seek(0)
        return cast(BinaryIO, spooled)

    def signed_url(self, key: str, *, expires_in: int) -> str:
        return f"memory://{key}?expires_in={expires_in}"


class SupabaseStorage:
    def __init__(
        self,
        base_url: str,
        service_key: str,
        bucket: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        if not base_url or not service_key or not bucket:
            raise ValueError("SUPABASE_URL, the service-role key and a bucket must all be set")
        self._base = base_url.rstrip("/") + "/storage/v1"
        self._key = service_key
        self._bucket = bucket
        self._client = httpx.Client(transport=transport, timeout=timeout_seconds)

    def _headers(self) -> dict[str, str]:
        return {"apikey": self._key, "authorization": f"Bearer {self._key}"}

    def _path(self, key: str) -> str:
        return f"{quote(self._bucket, safe='')}/{quote(key, safe='/')}"

    def _fail(
        self, what: str, exc: Exception | None = None, status: int | None = None
    ) -> StorageError:
        # Only the operation and a status code or exception class: no URL, key or body.
        suffix = f" ({status})" if status is not None else ""
        suffix = f" ({type(exc).__name__})" if exc is not None else suffix
        return StorageError(f"{what} failed{suffix}")

    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None:
        def body() -> Iterator[bytes]:
            while chunk := data.read(_CHUNK):
                yield chunk

        headers = {
            **self._headers(),
            "content-type": content_type,
            "content-length": str(size),
            "x-upsert": "false",
        }
        try:
            response = self._client.post(
                f"{self._base}/object/{self._path(key)}",
                content=body(),
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise self._fail("storing the file", exc) from None
        if response.status_code in (200, 201):
            return
        if _is_duplicate(response):
            return  # content-addressed: the same key holds the same bytes
        raise self._fail("storing the file", status=response.status_code)

    def open(self, key: str) -> BinaryIO:
        spooled = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            with self._client.stream(
                "GET",
                f"{self._base}/object/authenticated/{self._path(key)}",
                headers=self._headers(),
            ) as response:
                if response.status_code != 200:
                    raise self._fail("reading the file", status=response.status_code)
                for chunk in response.iter_bytes(_CHUNK):
                    spooled.write(chunk)
        except httpx.HTTPError as exc:
            spooled.close()
            raise self._fail("reading the file", exc) from None
        except StorageError:
            spooled.close()
            raise
        spooled.seek(0)
        return cast(BinaryIO, spooled)

    def signed_url(self, key: str, *, expires_in: int) -> str:
        try:
            response = self._client.post(
                f"{self._base}/object/sign/{self._path(key)}",
                json={"expiresIn": expires_in},
                headers=self._headers(),
            )
            if response.status_code != 200:
                raise self._fail("signing the file URL", status=response.status_code)
            signed = str(response.json()["signedURL"])
        except httpx.HTTPError as exc:
            raise self._fail("signing the file URL", exc) from None
        except (KeyError, ValueError):
            raise self._fail("signing the file URL") from None
        return f"{self._base}{signed}" if signed.startswith("/") else signed


def _is_duplicate(response: httpx.Response) -> bool:
    if response.status_code == 409:
        return True
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return str(body.get("error", "")).lower() == "duplicate"


@lru_cache
def _supabase_storage(url: str, key: str, bucket: str) -> SupabaseStorage:
    return SupabaseStorage(url, key, bucket)


def get_object_store() -> ObjectStore:
    """FastAPI dependency; tests override it with an InMemoryStore."""
    settings = get_settings()
    key = settings.supabase_service_role_key.get_secret_value()
    if not settings.supabase_url or not key:
        raise NotConfiguredError("File storage needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    return _supabase_storage(settings.supabase_url, key, settings.supabase_storage_bucket_imports)

"""Object storage for original files (R1-003, R1-048). Backend only.

Files live in private Supabase Storage buckets under `tenants/{tenant_id}/{random uuid}`
(docs/SECURITY.md section 3): the key is random per file version, never derived from the
content, and a file is never overwritten. The SHA-256 lives in the database.

The service-role key is a SecretStr. It is unwrapped once, inside the httpx client's default
headers, and nowhere else: not in an argument, a local variable, an error message or a log line
(CLAUDE.md section 9, rule 18). Every failure inside the adapter becomes a StorageError with
`from None` and a message of only the operation and an exception class or status code.
"""

import tempfile
from collections.abc import Iterator
from functools import lru_cache
from typing import BinaryIO, Protocol, cast
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.errors import NotConfiguredError, StorageError
from app.core.ids import uuid7

_CHUNK = 64 * 1024


def new_object_key(tenant_id: UUID) -> str:
    """A fresh random key for one stored file: `tenants/{tenant_id}/{uuid}`."""
    return f"tenants/{tenant_id}/{uuid7()}"


class ObjectStore(Protocol):
    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None:
        """Store the bytes under a new `key`. Never overwrites."""
        ...

    def open(self, key: str) -> BinaryIO:
        """The stored bytes, as a seekable binary file. The caller closes it."""
        ...

    def delete(self, key: str) -> None:
        """Remove an object (cleanup of a blob that lost an upload race). A missing object is
        not an error."""
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
        if key in self.objects:
            raise StorageError("the object already exists")
        self.objects[key] = body

    def open(self, key: str) -> BinaryIO:
        if key not in self.objects:
            raise StorageError("the object does not exist")
        spooled = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        spooled.write(self.objects[key])
        spooled.seek(0)
        return cast(BinaryIO, spooled)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def signed_url(self, key: str, *, expires_in: int) -> str:
        return f"memory://{key}?expires_in={expires_in}"


class SupabaseStorage:
    def __init__(
        self,
        base_url: str,
        service_key: SecretStr,
        bucket: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        if not base_url or not service_key.get_secret_value() or not bucket:
            raise StorageError("storage is not configured")
        self._base = base_url.rstrip("/") + "/storage/v1"
        self._bucket = bucket
        try:
            # The only place the key is unwrapped: the client carries it, we do not.
            self._client = httpx.Client(
                transport=transport,
                timeout=timeout_seconds,
                headers={
                    "apikey": service_key.get_secret_value(),
                    "authorization": f"Bearer {service_key.get_secret_value()}",
                },
            )
        except Exception as exc:
            raise StorageError(
                f"creating the storage client failed ({type(exc).__name__})"
            ) from None

    def __repr__(self) -> str:
        return f"SupabaseStorage(bucket={self._bucket!r})"

    def _path(self, key: str) -> str:
        return f"{quote(self._bucket, safe='')}/{quote(key, safe='/')}"

    @staticmethod
    def _fail(
        what: str, *, exc: Exception | None = None, status: int | None = None
    ) -> StorageError:
        # Only the operation and a status code or exception class: no URL, key or body.
        if exc is not None:
            return StorageError(f"{what} failed ({type(exc).__name__})")
        if status is not None:
            return StorageError(f"{what} failed ({status})")
        return StorageError(f"{what} failed")

    def put(self, key: str, data: BinaryIO, *, size: int, content_type: str) -> None:
        def body() -> Iterator[bytes]:
            while chunk := data.read(_CHUNK):
                yield chunk

        try:
            response = self._client.post(
                f"{self._base}/object/{self._path(key)}",
                content=body(),
                headers={
                    "content-type": content_type,
                    "content-length": str(size),
                    "x-upsert": "false",
                },
            )
            status = response.status_code
        except Exception as exc:
            raise self._fail("storing the file", exc=exc) from None
        if status in (200, 201):
            return
        raise self._fail("storing the file", status=status)

    def open(self, key: str) -> BinaryIO:
        spooled = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            with self._client.stream(
                "GET", f"{self._base}/object/authenticated/{self._path(key)}"
            ) as response:
                if response.status_code != 200:
                    raise self._fail("reading the file", status=response.status_code)
                for chunk in response.iter_bytes(_CHUNK):
                    spooled.write(chunk)
        except StorageError:
            spooled.close()
            raise
        except Exception as exc:
            spooled.close()
            raise self._fail("reading the file", exc=exc) from None
        spooled.seek(0)
        return cast(BinaryIO, spooled)

    def delete(self, key: str) -> None:
        try:
            response = self._client.delete(f"{self._base}/object/{self._path(key)}")
            status = response.status_code
        except Exception as exc:
            raise self._fail("deleting the file", exc=exc) from None
        if status not in (200, 204, 404):
            raise self._fail("deleting the file", status=status)

    def signed_url(self, key: str, *, expires_in: int) -> str:
        try:
            response = self._client.post(
                f"{self._base}/object/sign/{self._path(key)}", json={"expiresIn": expires_in}
            )
            status = response.status_code
            signed = str(response.json()["signedURL"]) if status == 200 else ""
        except Exception as exc:
            raise self._fail("signing the file URL", exc=exc) from None
        if status != 200 or not signed:
            raise self._fail("signing the file URL", status=status)
        return f"{self._base}{signed}" if signed.startswith("/") else signed


@lru_cache
def _supabase_storage(url: str, key: SecretStr, bucket: str) -> SupabaseStorage:
    return SupabaseStorage(url, key, bucket)


def get_object_store() -> ObjectStore:
    """FastAPI dependency; tests override it with an InMemoryStore."""
    settings = get_settings()
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key.get_secret_value():
        raise NotConfiguredError("File storage needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    return _supabase_storage(settings.supabase_url, key, settings.supabase_storage_bucket_imports)

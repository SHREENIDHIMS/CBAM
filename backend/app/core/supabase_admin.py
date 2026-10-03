"""Supabase Auth admin calls (inviting users). Uses the service-role key: backend only.

CLAUDE.md section 9 and rule 18: the key never reaches the frontend, a log line or an error.
"""

import re
from typing import Protocol
from uuid import UUID

import httpx

from app.core.config import get_settings
from app.core.errors import AuthAdminError, InvalidRequestError, NotConfiguredError


class AuthAdmin(Protocol):
    def invite(self, email: str, *, redirect_to: str | None) -> UUID:
        """Create the person in Supabase Auth (or find them) and email an invitation."""
        ...


class HttpSupabaseAdmin:
    def __init__(
        self,
        base_url: str,
        service_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        if not base_url or not service_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set")
        self._base = base_url.rstrip("/") + "/auth/v1"
        self._key = service_key
        self._client = httpx.Client(transport=transport, timeout=timeout_seconds)

    def _headers(self) -> dict[str, str]:
        return {"apikey": self._key, "authorization": f"Bearer {self._key}"}

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "[redacted]")[:200]

    def invite(self, email: str, *, redirect_to: str | None) -> UUID:
        params = {"redirect_to": redirect_to} if redirect_to else None
        try:
            response = self._client.post(
                f"{self._base}/invite",
                params=params,
                json={"email": email},
                headers=self._headers(),
            )
            if response.status_code == 200:
                return UUID(str(response.json()["id"]))
            code = _error_code(response)
            if response.status_code == 422 and code == "email_exists":
                return self._find(email)
            if response.status_code in (400, 422):
                raise InvalidRequestError("The email address was not accepted")
            raise AuthAdminError(f"identity provider answered {response.status_code}")
        except (InvalidRequestError, AuthAdminError):
            raise
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise AuthAdminError(self._scrub(type(exc).__name__)) from None

    def _find(self, email: str) -> UUID:
        page = 1
        while page <= 50:
            response = self._client.get(
                f"{self._base}/admin/users",
                params={"page": page, "per_page": 200},
                headers=self._headers(),
            )
            if response.status_code != 200:
                raise AuthAdminError(f"identity provider answered {response.status_code}")
            users = response.json().get("users", [])
            for user in users:
                if str(user.get("email", "")).lower() == email.lower():
                    return UUID(str(user["id"]))
            if len(users) < 200:
                break
            page += 1
        raise AuthAdminError("the existing account could not be found")


def _error_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("error_code") or re.sub(r"\W+", "_", str(body.get("msg", ""))).lower())


def get_auth_admin() -> AuthAdmin:
    """FastAPI dependency; tests override it with a fake."""
    settings = get_settings()
    key = settings.supabase_service_role_key.get_secret_value()
    if not settings.supabase_url or not key:
        raise NotConfiguredError("Inviting users needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    return HttpSupabaseAdmin(settings.supabase_url, key)

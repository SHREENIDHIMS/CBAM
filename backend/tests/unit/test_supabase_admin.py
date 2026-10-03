"""The Supabase admin client: invite by email using the service-role key (backend only)."""

import json
from uuid import UUID

import httpx
import pytest

from app.core.errors import InvalidRequestError
from app.core.supabase_admin import AuthAdminError, HttpSupabaseAdmin

URL = "http://127.0.0.1:54321"
KEY = "service-role-secret-value"
UID = "22222222-2222-2222-2222-222222222222"


def _admin(handler) -> HttpSupabaseAdmin:  # type: ignore[no-untyped-def]
    return HttpSupabaseAdmin(URL, KEY, transport=httpx.MockTransport(handler))


def test_invite_posts_the_email_with_the_service_key() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["apikey"] = request.headers["apikey"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": UID, "email": "new@example.test"})

    user_id = _admin(handler).invite(
        "new@example.test", redirect_to="https://app.example/reset-password/update"
    )
    assert user_id == UUID(UID)
    assert (
        seen["url"]
        == f"{URL}/auth/v1/invite?redirect_to=https%3A%2F%2Fapp.example%2Freset-password%2Fupdate"
    )
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["apikey"] == KEY
    assert seen["body"] == {"email": "new@example.test"}


def test_existing_user_is_found_by_email() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/invite"):
            return httpx.Response(
                422, json={"error_code": "email_exists", "msg": "already registered"}
            )
        return httpx.Response(
            200,
            json={
                "users": [
                    {"id": "33333333-3333-3333-3333-333333333333", "email": "other@example.test"},
                    {"id": UID, "email": "Known@Example.test"},
                ]
            },
        )

    assert _admin(handler).invite("known@example.test", redirect_to=None) == UUID(UID)


def test_unknown_failure_is_a_bad_gateway_without_leaking_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"boom {KEY}")

    with pytest.raises(AuthAdminError) as exc:
        _admin(handler).invite("a@example.test", redirect_to=None)
    assert exc.value.status == 502
    assert KEY not in str(exc.value)
    assert KEY not in exc.value.detail


def test_network_failure_is_a_bad_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(AuthAdminError):
        _admin(handler).invite("a@example.test", redirect_to=None)


def test_rejected_email_is_a_422_for_the_caller() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error_code": "email_address_invalid", "msg": "bad"})

    with pytest.raises(InvalidRequestError):
        _admin(handler).invite("a@example.test", redirect_to=None)


def test_missing_configuration_is_refused() -> None:
    with pytest.raises(ValueError, match="SUPABASE"):
        HttpSupabaseAdmin("", "", transport=None)

"""Supabase JWT verification (R1-042, CLAUDE.md rule 18 and section 4).

FastAPI verifies the token: signature (project JWKS), expiry, audience, issuer. Privileged
roles need an `aal2` token (MFA passed). Sensitive actions need a recent login. Passwords and
MFA secrets stay in Supabase Auth; we never see them.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.core.errors import AuthenticationError, MfaRequiredError, RecentAuthRequiredError
from app.core.permissions import mfa_required

_ASYMMETRIC = ("ES256", "RS256", "EdDSA")


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    aal: str  # "aal1" or "aal2"
    email: str | None  # personal data: never log it
    last_login: datetime | None  # latest sign-in or MFA step, from the amr claim


class KeyResolver(Protocol):
    def signing_key(self, token: str) -> Any:
        """The public key that should have signed `token`."""
        ...


class StaticKeyResolver:
    """A fixed key; used in tests."""

    def __init__(self, key: Any) -> None:
        self._key = key

    def signing_key(self, token: str) -> Any:
        return self._key


class JwksKeyResolver:
    """Keys from the Supabase project JWKS, cached by PyJWKClient."""

    def __init__(self, jwks_url: str) -> None:
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=600)

    def signing_key(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


class JwtVerifier:
    def __init__(
        self,
        *,
        resolver: KeyResolver,
        issuer: str,
        audience: str,
        shared_secret: str = "",
    ) -> None:
        self._resolver = resolver
        self._issuer = issuer
        self._audience = audience
        self._secret = shared_secret

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            alg = jwt.get_unverified_header(token).get("alg")
            if alg in _ASYMMETRIC:
                key: Any = self._resolver.signing_key(token)
            elif alg == "HS256" and self._secret:
                # Local development only (the setting is refused in production).
                key = self._secret
            else:
                raise AuthenticationError("Unsupported token algorithm")
            claims = jwt.decode(
                token,
                key,
                algorithms=[alg] if isinstance(alg, str) else [],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            user_id = UUID(str(claims["sub"]))
        except AuthenticationError:
            raise
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise AuthenticationError("The access token is not valid") from exc
        return AuthenticatedUser(
            user_id=user_id,
            aal="aal2" if claims.get("aal") == "aal2" else "aal1",
            email=claims.get("email"),
            last_login=_last_login(claims.get("amr")),
        )


def _last_login(amr: Any) -> datetime | None:
    stamps: list[int] = []
    if isinstance(amr, list):
        for step in amr:
            if isinstance(step, dict) and isinstance(step.get("timestamp"), int):
                stamps.append(step["timestamp"])
    return datetime.fromtimestamp(max(stamps), tz=UTC) if stamps else None


def require_mfa_for_roles(user: AuthenticatedUser, roles: Iterable[str]) -> None:
    """Privileged roles need a token from a session that passed MFA (aal2)."""
    if mfa_required(roles) and user.aal != "aal2":
        raise MfaRequiredError("This role requires multi-factor authentication")


def require_recent_auth(user: AuthenticatedUser, *, now: datetime, max_age: timedelta) -> None:
    """Sensitive actions need a login (or MFA step) within `max_age`. Fails closed."""
    if user.last_login is None or now - user.last_login > max_age:
        raise RecentAuthRequiredError("Sign in again to confirm this action")

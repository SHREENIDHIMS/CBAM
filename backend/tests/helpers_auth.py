"""Mint Supabase-style access tokens with a throwaway key (aal1 / aal2, login age)."""

import time
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.auth import JwtVerifier, StaticKeyResolver

ISSUER = "http://127.0.0.1:54321/auth/v1"
AUDIENCE = "authenticated"
KEY = ec.generate_private_key(ec.SECP256R1())


def verifier() -> JwtVerifier:
    return JwtVerifier(
        resolver=StaticKeyResolver(KEY.public_key()), issuer=ISSUER, audience=AUDIENCE
    )


def token_for(
    user_id: UUID, *, aal: str = "aal1", login_age_s: int = 0, email: str | None = None
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "aal": aal,
        "amr": [{"method": "password", "timestamp": now - login_age_s}],
    }
    if email:
        claims["email"] = email
    return jwt.encode(claims, KEY, algorithm="ES256")


def bearer(user_id: UUID, **kwargs: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user_id, **kwargs)}"}

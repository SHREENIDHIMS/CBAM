"""R1-042: Supabase JWT verification, aal2 for privileged roles, recent-login check.

Tokens are minted here with a throwaway key, as the handbook requires (aal1 vs aal2).
"""

import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.auth import (
    JwtVerifier,
    StaticKeyResolver,
    require_mfa_for_roles,
    require_recent_auth,
)
from app.core.errors import AuthenticationError, MfaRequiredError, RecentAuthRequiredError

ISSUER = "http://127.0.0.1:54321/auth/v1"
AUDIENCE = "authenticated"
USER = "11111111-1111-1111-1111-111111111111"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def _token(
    *,
    key: ec.EllipticCurvePrivateKey = KEY,
    alg: str = "ES256",
    aal: str = "aal1",
    age_s: int = 0,
    exp_in_s: int = 3600,
    aud: str = AUDIENCE,
    iss: str = ISSUER,
    sub: str | None = USER,
    amr: list[dict[str, Any]] | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "aud": aud,
        "iss": iss,
        "iat": now - age_s,
        "exp": now + exp_in_s,
        "aal": aal,
        "amr": amr if amr is not None else [{"method": "password", "timestamp": now - age_s}],
        "email": "someone@example.test",
    }
    if sub is not None:
        claims["sub"] = sub
    return jwt.encode(claims, key, algorithm=alg)


def _verifier(**kwargs: Any) -> JwtVerifier:
    return JwtVerifier(
        resolver=StaticKeyResolver(KEY.public_key()),
        issuer=ISSUER,
        audience=AUDIENCE,
        **kwargs,
    )


def test_valid_token_gives_user_and_assurance_level() -> None:
    user = _verifier().verify(_token(aal="aal2"))
    assert user.user_id == UUID(USER)
    assert user.aal == "aal2"
    assert user.email == "someone@example.test"


def test_expired_token_is_401() -> None:
    with pytest.raises(AuthenticationError):
        _verifier().verify(_token(exp_in_s=-10))


def test_wrong_audience_and_issuer_are_refused() -> None:
    with pytest.raises(AuthenticationError):
        _verifier().verify(_token(aud="someone-else"))
    with pytest.raises(AuthenticationError):
        _verifier().verify(_token(iss="http://evil.example/auth/v1"))


def test_token_signed_with_another_key_is_refused() -> None:
    with pytest.raises(AuthenticationError):
        _verifier().verify(_token(key=OTHER_KEY))


def test_missing_subject_is_refused() -> None:
    with pytest.raises(AuthenticationError):
        _verifier().verify(_token(sub=None))


def test_subject_must_be_a_uuid() -> None:
    with pytest.raises(AuthenticationError):
        _verifier().verify(_token(sub="not-a-uuid"))


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_is_refused(garbage: str) -> None:
    with pytest.raises(AuthenticationError):
        _verifier().verify(garbage)


def test_alg_none_is_refused() -> None:
    header = jwt.utils.base64url_encode(b'{"alg":"none","typ":"JWT"}').decode()
    body = jwt.utils.base64url_encode(
        f'{{"sub":"{USER}","aud":"{AUDIENCE}","iss":"{ISSUER}","exp":{int(time.time()) + 600}}}'.encode()
    ).decode()
    with pytest.raises(AuthenticationError):
        _verifier().verify(f"{header}.{body}.")


def test_hs256_signed_with_the_public_key_is_refused() -> None:
    """Key-confusion attack: HS256 using the public key bytes as the shared secret.

    PyJWT refuses to build this token itself, so forge it by hand with the standard library.
    """
    public_pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header = jwt.utils.base64url_encode(b'{"alg":"HS256","typ":"JWT"}').decode()
    claims = (
        f'{{"sub":"{USER}","aud":"{AUDIENCE}","iss":"{ISSUER}",'
        f'"exp":{int(time.time()) + 600},"aal":"aal2"}}'
    )
    body = jwt.utils.base64url_encode(claims.encode()).decode()
    signature = hmac.new(public_pem, f"{header}.{body}".encode(), hashlib.sha256).digest()
    forged = f"{header}.{body}.{jwt.utils.base64url_encode(signature).decode()}"
    with pytest.raises(AuthenticationError):
        _verifier().verify(forged)


def test_local_shared_secret_is_accepted_only_when_configured() -> None:
    secret = "local-dev-secret-at-least-32-characters-long"  # noqa: S105 - dummy test value
    token = jwt.encode(
        {"sub": USER, "aud": AUDIENCE, "iss": ISSUER, "exp": int(time.time()) + 600, "aal": "aal1"},
        secret,
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        _verifier().verify(token)
    assert _verifier(shared_secret=secret).verify(token).user_id == UUID(USER)


def test_missing_aal_claim_is_treated_as_aal1() -> None:
    now = int(time.time())
    token = jwt.encode(
        {"sub": USER, "aud": AUDIENCE, "iss": ISSUER, "exp": now + 600}, KEY, algorithm="ES256"
    )
    assert _verifier().verify(token).aal == "aal1"


# --- MFA for privileged roles -------------------------------------------------------------


def test_privileged_role_without_mfa_is_refused() -> None:
    """Phase 1 exit gate: privileged role without MFA is refused."""
    user = _verifier().verify(_token(aal="aal1"))
    for role in ("operations", "reviewer", "approver", "domain_owner", "platform_admin"):
        with pytest.raises(MfaRequiredError):
            require_mfa_for_roles(user, [role])


def test_privileged_role_with_mfa_is_allowed() -> None:
    user = _verifier().verify(_token(aal="aal2"))
    require_mfa_for_roles(user, ["operations"])


def test_unprivileged_roles_do_not_need_mfa() -> None:
    user = _verifier().verify(_token(aal="aal1"))
    require_mfa_for_roles(user, ["client_admin", "tax_agent"])


def test_one_privileged_role_among_others_triggers_mfa() -> None:
    user = _verifier().verify(_token(aal="aal1"))
    with pytest.raises(MfaRequiredError):
        require_mfa_for_roles(user, ["client_admin", "approver"])


# --- recent login -------------------------------------------------------------------------


NOW = datetime.now(UTC)


def test_recent_login_passes_within_the_window() -> None:
    user = _verifier().verify(_token(age_s=5 * 60))
    require_recent_auth(user, now=NOW, max_age=timedelta(minutes=15))


def test_old_login_is_refused_even_with_a_fresh_token() -> None:
    """A refreshed access token has a new iat but keeps the original login time in amr."""
    old_login = int(time.time()) - 3 * 3600
    user = _verifier().verify(_token(age_s=0, amr=[{"method": "password", "timestamp": old_login}]))
    with pytest.raises(RecentAuthRequiredError):
        require_recent_auth(user, now=NOW, max_age=timedelta(minutes=15))


def test_mfa_step_counts_as_a_recent_login() -> None:
    now = int(time.time())
    user = _verifier().verify(
        _token(
            aal="aal2",
            amr=[
                {"method": "password", "timestamp": now - 3 * 3600},
                {"method": "totp", "timestamp": now - 60},
            ],
        )
    )
    require_recent_auth(user, now=NOW, max_age=timedelta(minutes=15))


def test_no_amr_means_not_recent() -> None:
    now = int(time.time())
    token = jwt.encode(
        {"sub": USER, "aud": AUDIENCE, "iss": ISSUER, "exp": now + 600, "iat": now},
        KEY,
        algorithm="ES256",
    )
    user = _verifier().verify(token)
    with pytest.raises(RecentAuthRequiredError):
        require_recent_auth(user, now=NOW, max_age=timedelta(minutes=15))

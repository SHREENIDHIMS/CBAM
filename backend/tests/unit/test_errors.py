"""Domain errors map to problem+json (docs/TECHNICAL_SPEC.md section 10, API_SPEC)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import (
    NotPermittedError,
    RuleBlockedError,
    SourceNotActiveError,
    StaleVersionError,
    TenantMismatchError,
    install_error_handlers,
)


class _Body(BaseModel):
    n: int


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app, type_base="https://cbam.example/errors/")

    @app.get("/blocked")
    def blocked() -> None:
        raise RuleBlockedError(
            "Default to actual is not allowed", rule_id="R3-014", source_id="FA2026-S17-P8-2"
        )

    @app.get("/stale")
    def stale() -> None:
        raise StaleVersionError("Row changed")

    @app.get("/denied")
    def denied() -> None:
        raise NotPermittedError("No")

    @app.get("/tenant")
    def tenant() -> None:
        raise TenantMismatchError()

    @app.get("/source")
    def source() -> None:
        raise SourceNotActiveError("Draft law", source_id="DRAFT-1")

    @app.post("/body")
    def body(b: _Body) -> None:
        return None

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    return TestClient(app, raise_server_exceptions=False)


def test_rule_blocked_carries_rule_and_source() -> None:
    r = _client().get("/blocked")
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"] == "https://cbam.example/errors/rule-blocked"
    assert body["rule_id"] == "R3-014"
    assert body["source_id"] == "FA2026-S17-P8-2"
    assert body["status"] == 409
    assert body["instance"] == "/blocked"


def test_status_codes() -> None:
    c = _client()
    assert c.get("/stale").status_code == 409
    assert c.get("/denied").status_code == 403
    assert c.get("/tenant").status_code == 404  # never confirm another tenant's row exists
    assert c.get("/source").status_code == 409


def test_validation_error_is_problem_json_with_errors() -> None:
    r = _client().post("/body", json={"n": "x"})
    assert r.status_code == 422
    assert r.json()["type"].endswith("/validation-error")
    assert r.json()["errors"][0]["loc"][-1] == "n"


def test_unhandled_error_does_not_leak_details() -> None:
    r = _client().get("/boom")
    assert r.status_code == 500
    assert "secret internal detail" not in r.text
    assert r.json()["type"].endswith("/internal-error")

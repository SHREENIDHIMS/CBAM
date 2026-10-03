from fastapi.testclient import TestClient

from app.main import app


def test_live_and_ready() -> None:
    client = TestClient(app)
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200


def test_request_id_is_echoed_and_generated() -> None:
    client = TestClient(app)
    assert (
        client.get("/health/live", headers={"x-request-id": "abc"}).headers["x-request-id"] == "abc"
    )
    assert len(client.get("/health/live").headers["x-request-id"]) == 32


def test_unknown_route_is_problem_json() -> None:
    r = TestClient(app).get("/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")

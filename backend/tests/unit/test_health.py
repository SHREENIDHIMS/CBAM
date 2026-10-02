from fastapi.testclient import TestClient

from app.main import app


def test_live_and_ready() -> None:
    client = TestClient(app)
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").status_code == 200

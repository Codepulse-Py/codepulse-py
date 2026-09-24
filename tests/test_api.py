from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_ok():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_reports_configured_deps(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    deps = TestClient(app).get("/health").json()["deps"]
    assert deps["redis"] is True
    assert deps["database"] is False

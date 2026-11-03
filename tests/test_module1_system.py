"""Module 1 tests: health, meta, error format, CORS, frontend serving."""
from app.core.config import settings

API = settings.API_V1_PREFIX


def test_health_ok(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["database"]["version"]


def test_meta_has_frontend_values(client):
    r = client.get(f"{API}/meta")
    assert r.status_code == 200
    m = r.json()
    assert m["enums"]["task_statuses"] == [
        "Not Started", "In Progress", "Submitted for Review",
        "Completed", "Delayed", "On Hold",
    ]
    assert m["enums"]["priorities"] == ["High", "Medium", "Low"]
    assert m["enums"]["leave_types"] == ["Annual", "Sick", "Casual", "Unpaid"]
    assert m["enums"]["roles"] == ["admin", "teamlead", "employee"]
    assert m["enums"]["platforms"] == ["web", "android", "ios"]
    assert m["workload"] == {"weekly_capacity_hours": 40, "busy_threshold_hours": 30}
    assert m["timezone"] == "Asia/Kolkata"


def test_unknown_route_uses_common_error_format(client):
    r = client.get(f"{API}/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found", "code": "NOT_FOUND", "fields": None}


def test_wrong_method_uses_common_error_format(client):
    r = client.post(f"{API}/health")
    assert r.status_code == 405
    assert r.json()["code"] == "METHOD_NOT_ALLOWED"


def test_cors_allows_configured_origin(client):
    origin = settings.CORS_ORIGINS[0]
    r = client.options(f"{API}/health", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin


def test_cors_blocks_unknown_origin(client):
    r = client.options(f"{API}/health", headers={
        "Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") is None


def test_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_frontend_served(client):
    r = client.get("/app/")
    assert r.status_code == 200
    assert "Employee360" in r.text

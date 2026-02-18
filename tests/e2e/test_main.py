from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "taskflow-api", "status": "ok"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_request_id_header_propagation() -> None:
    request_id = "req-test-123"
    response = client.get("/health", headers={"X-Request-Id": request_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-Id") == request_id

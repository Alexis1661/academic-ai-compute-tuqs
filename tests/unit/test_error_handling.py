"""Every non-2xx response uses the ErrorBody envelope; no stack traces leak."""
from fastapi.testclient import TestClient

from src.composition import get_ingest_token_event
from src.domain.exceptions import StorageUnavailableError
from src.main import app

ERROR_KEYS = {"error_code", "message", "correlation_id", "timestamp", "details"}


def test_unknown_route_returns_error_body(client):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["error_code"] == "ERR_NOT_FOUND"
    assert body["timestamp"] == "2026-10-25T12:00:00Z"


def test_correlation_id_is_echoed(client):
    response = client.post(
        "/api/v1/tokens/events",
        json={"user_id": "sam", "prompt_tokens": 0, "completion_tokens": 0},
        headers={"X-Correlation-ID": "req-123"},
    )
    assert response.json()["correlation_id"] == "req-123"
    assert response.headers["X-Correlation-ID"] == "req-123"


def test_storage_unavailable_fails_closed_with_503(client):
    class FailingUseCase:
        def execute(self, command):
            raise StorageUnavailableError()

    app.dependency_overrides[get_ingest_token_event] = lambda: FailingUseCase()
    response = client.post(
        "/api/v1/tokens/events", json={"user_id": "sam", "prompt_tokens": 1, "completion_tokens": 1}
    )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error_code"] == "ERR_STORAGE_UNAVAILABLE"


def test_unexpected_error_returns_structured_500(client):
    class BrokenUseCase:
        def execute(self, command):
            raise RuntimeError("boom: internal detail")

    app.dependency_overrides[get_ingest_token_event] = lambda: BrokenUseCase()
    with TestClient(app, raise_server_exceptions=False) as raw_client:
        response = raw_client.post(
            "/api/v1/tokens/events",
            json={"user_id": "sam", "prompt_tokens": 1, "completion_tokens": 1},
        )
    assert response.status_code == 500
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["error_code"] == "ERR_INTERNAL"
    assert "boom" not in response.text

"""Every non-2xx response uses the ErrorBody envelope; no stack traces leak."""
from fastapi.testclient import TestClient

import pytest
from sqlalchemy.orm import sessionmaker

from src.adapters.outbound.db import build_engine, get_db
from src.composition import get_clock, get_ingest_token_event
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
        json={"user_id": "sam", "subject_id": "CS-480", "prompt_tokens": 0, "completion_tokens": 0},
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
        "/api/v1/tokens/events",
        json={"user_id": "sam", "subject_id": "CS-480", "prompt_tokens": 1, "completion_tokens": 1},
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
            json={"user_id": "sam", "subject_id": "CS-480", "prompt_tokens": 1, "completion_tokens": 1},
        )
    assert response.status_code == 500
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["error_code"] == "ERR_INTERNAL"
    assert "boom" not in response.text


@pytest.fixture
def unreachable_db(tmp_path):
    """Session bound to a SQLite file in a directory that does not exist: every query fails."""
    engine = build_engine(f"sqlite:///{(tmp_path / 'missing-dir' / 'tuqs.db').as_posix()}")
    session = sessionmaker(bind=engine)()
    app.dependency_overrides[get_db] = lambda: session
    yield
    session.close()
    engine.dispose()


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/api/v1/tokens/balance/sam", None),
    ("post", "/api/v1/tokens/check-allowance", {"user_id": "sam", "requested_tokens": 10}),
])
def test_read_paths_fail_closed_on_real_database_error(client, unreachable_db, method, path, payload):
    """AD-7: a real OperationalError on quota reads becomes 503 + Retry-After, never 500."""
    response = client.request(method, path, json=payload)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error_code"] == "ERR_STORAGE_UNAVAILABLE"


@pytest.mark.parametrize("supplied", ["bad id with spaces", "x" * 129, "evil;Injected=yes"])
def test_unsafe_correlation_id_is_replaced(client, supplied):
    response = client.get("/api/v1/does-not-exist", headers={"X-Correlation-ID": supplied})
    correlation_id = response.json()["correlation_id"]
    assert correlation_id != supplied
    assert len(correlation_id) == 36  # generated UUID
    assert response.headers["X-Correlation-ID"] == correlation_id


def test_storage_error_subclass_still_maps_to_503(client):
    class PoolExhaustedError(StorageUnavailableError):
        pass

    class FailingUseCase:
        def execute(self, command):
            raise PoolExhaustedError()

    app.dependency_overrides[get_ingest_token_event] = lambda: FailingUseCase()
    response = client.post(
        "/api/v1/tokens/events",
        json={"user_id": "sam", "subject_id": "CS-480", "prompt_tokens": 1, "completion_tokens": 1},
    )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"


def test_error_handler_survives_a_failing_clock(client):
    class BrokenClock:
        def now(self):
            raise RuntimeError("clock down")

    app.dependency_overrides[get_clock] = lambda: BrokenClock()
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error_code"] == "ERR_NOT_FOUND"

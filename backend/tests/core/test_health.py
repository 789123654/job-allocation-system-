"""/ready (app/core/health.py): fail-closed, no information disclosure, bounded work.

ASVS 13.4.5, 16.5.1, 16.5.3 and Denial_of_Service_Cheat_Sheet.md. The DB engine is always a
substituted fake or a SQLite file — never the real DATABASE_URL.
"""

import threading
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from app.core.health import readiness_probe
from app.main import app


class _Connection:
    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, *_args: object, **_kwargs: object) -> None:
        return None


class _FakeEngine:
    """Stands in for `app.core.db.engine`; `behavior` runs on every connect()."""

    def __init__(self, behavior: Callable[[], object] | None = None) -> None:
        self.calls = 0
        self._behavior = behavior

    def connect(self) -> _Connection:
        self.calls += 1
        if self._behavior is not None:
            self._behavior()
        return _Connection()


@pytest.fixture(autouse=True)
def _clean_probe() -> Generator[None]:  # pyright: ignore[reportUnusedFunction]
    readiness_probe.reset()
    yield
    readiness_probe.reset()


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _use(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    monkeypatch.setattr("app.core.db.engine", engine)


def test_health_stays_liveness_only_and_never_touches_the_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine(behavior=lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    _use(monkeypatch, engine)
    response = client.get("/health")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert engine.calls == 0


def test_ready_is_200_when_the_database_answers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, _FakeEngine())
    response = client.get("/ready")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


def test_ready_fails_closed_on_any_error_and_leaks_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode() -> None:
        raise RuntimeError("password=SENTINEL-PW host=SENTINEL-HOST.internal port=5432")

    _use(monkeypatch, _FakeEngine(behavior=explode))
    response = client.get("/ready")
    assert (response.status_code, response.json()) == (503, {"status": "unavailable"})
    everything = response.text + "".join(f"{k}: {v}" for k, v in response.headers.items())
    assert "SENTINEL" not in everything


def test_ready_treats_even_a_baseexception_style_failure_type_as_not_ready(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode() -> None:
        raise OSError("connection refused")

    _use(monkeypatch, _FakeEngine(behavior=explode))
    assert client.get("/ready").status_code == 503


def test_rapid_calls_cause_one_database_query_not_one_per_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine()
    _use(monkeypatch, engine)
    assert [client.get("/ready").status_code for _ in range(10)] == [200] * 10
    assert engine.calls == 1


def test_a_different_engine_is_never_answered_from_another_engines_cache(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, _FakeEngine())
    assert client.get("/ready").status_code == 200

    def explode() -> None:
        raise RuntimeError("down")

    _use(monkeypatch, _FakeEngine(behavior=explode))
    assert client.get("/ready").status_code == 503  # not the cached 200 from the healthy engine


def test_a_hung_database_yields_503_quickly_and_only_one_blocked_attempt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """20 concurrent probes against a hung DB must not each park a thread (Denial_of_Service)."""
    release = threading.Event()
    engine = _FakeEngine(behavior=lambda: release.wait(30))
    _use(monkeypatch, engine)
    try:
        started = time.monotonic()
        with ThreadPoolExecutor(20) as pool:
            statuses = list(pool.map(lambda _: client.get("/ready").status_code, range(20)))
        elapsed = time.monotonic() - started
        assert statuses == [503] * 20
        assert elapsed < 8  # bounded by the probe timeout, not the 30s hang
        assert engine.calls == 1  # single-flight: never a second blocked attempt
    finally:
        release.set()


def test_a_saturated_pool_is_reported_immediately_without_queueing_for_a_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path}/ready.db", poolclass=QueuePool, pool_size=2, max_overflow=1
    )
    held = [engine.connect() for _ in range(3)]  # pool_size 2 + overflow 1 => full
    _use(monkeypatch, engine)
    try:
        started = time.monotonic()
        response = client.get("/ready")
        assert (response.status_code, response.json()) == (503, {"status": "unavailable"})
        assert time.monotonic() - started < 1.0  # did NOT wait for pool_timeout to expire
    finally:
        for connection in held:
            connection.close()
        engine.dispose()


def test_ready_carries_a_request_id_and_the_security_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, _FakeEngine())
    response = client.get("/ready")
    headers: dict[str, Any] = dict(response.headers)
    assert "x-request-id" in headers
    assert headers["cache-control"] == "no-store"

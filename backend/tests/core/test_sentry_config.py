"""core/sentry_config.py: what a captured Sentry error event may contain.

The behaviour tests build a throwaway FastAPI app AFTER `sentry_sdk.init(...)` (the integration
auto-instruments on init, as app/main.py documents), send a request carrying client data and a
Bearer token to a route that fails, and inspect the event Sentry WOULD send — captured in-process
after the production `before_send`, never transmitted. Without the options in sentry_config the same
request leaks the body, frame variables and the token (verified 2026-09-19; negative control in
docs/SECURITY_AUDIT_CHECKLIST.md).
"""

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db import engine
from app.core.sentry_config import scrub_event, sentry_init_kwargs

_BODY_SECRET = "CLIENT-DESC-SENTINEL-91c2"
_TOKEN_SECRET = "TOKEN-SENTINEL-4be7"

_NEEDS_PG = pytest.mark.skipif(
    not (os.environ.get("TEST_DATABASE_URL") and os.environ.get("TEST_MIGRATIONS_DATABASE_URL")),
    reason="needs a real Postgres — TEST_DATABASE_URL/TEST_MIGRATIONS_DATABASE_URL (CI does)",
)


class _Body(BaseModel):
    title: str
    description: str


@pytest.fixture
def captured() -> Generator[list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    kwargs = sentry_init_kwargs(
        dsn="http://key@localhost:9/1", release="build-1", environment="test"
    )
    real_scrub = kwargs["before_send"]

    def capture(event: dict[str, Any], hint: dict[str, Any]) -> None:
        scrubbed = real_scrub(event, hint)  # exactly what production runs, then keep it locally
        if scrubbed is not None:
            events.append(scrubbed)

    kwargs["before_send"] = capture
    sentry_sdk.init(**kwargs)
    yield events
    sentry_sdk.get_client().close(timeout=0)
    sentry_sdk.init()  # back to a disabled client for every other test


def _post_failing_request(app: FastAPI) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/tasks",
            json={"title": "T", "description": _BODY_SECRET},
            headers={"Authorization": f"Bearer {_TOKEN_SECRET}"},
        )
    assert response.status_code == 500


def _app_whose_route_raises() -> FastAPI:
    app = FastAPI()

    @app.post("/tasks")
    def create(body: _Body) -> None:  # pyright: ignore[reportUnusedFunction]
        client_note = body.description  # a local variable holding client data
        raise RuntimeError("boom" + client_note[:0])

    return app


def test_an_error_event_carries_no_request_body_no_frame_variables_and_no_token(
    captured: list[dict[str, Any]],
) -> None:
    _post_failing_request(_app_whose_route_raises())
    (event,) = captured
    serialized = json.dumps(event, default=str)
    assert _BODY_SECRET not in serialized
    assert _TOKEN_SECRET not in serialized


def test_the_event_is_still_useful_for_debugging(captured: list[dict[str, Any]]) -> None:
    _post_failing_request(_app_whose_route_raises())
    (event,) = captured
    (exception,) = event["exception"]["values"]
    assert exception["type"] == "RuntimeError"
    assert exception["value"] == "boom"
    frames = exception["stacktrace"]["frames"]
    assert any(frame["function"] == "create" for frame in frames)
    assert event["release"] == "build-1"
    assert event["environment"] == "test"
    assert event["request"]["method"] == "POST"
    assert "vars" not in frames[-1]


@_NEEDS_PG
def test_a_database_error_event_carries_neither_the_value_nor_the_body(
    captured: list[dict[str, Any]],
) -> None:
    app = FastAPI()

    @app.post("/tasks")
    def create(body: _Body) -> None:  # pyright: ignore[reportUnusedFunction]
        with engine.connect() as conn:
            conn.execute(text("SELECT CAST(:v AS uuid)"), {"v": body.description})

    _post_failing_request(app)
    (event,) = captured
    serialized = json.dumps(event, default=str)
    assert _BODY_SECRET not in serialized
    assert "psycopg" in serialized  # the error class is still reported


def test_scrub_event_redacts_database_text_in_every_free_text_field() -> None:
    db_text = (
        "(psycopg.errors.UniqueViolation) dup\nDETAIL:  Key (name)=(SECRET-7f3a) already exists."
    )
    event: dict[str, Any] = {
        "exception": {"values": [{"type": "IntegrityError", "value": db_text}]},
        "logentry": {"message": db_text, "formatted": db_text},
        "message": db_text,
        "breadcrumbs": {"values": [{"category": "log", "message": db_text}]},
    }
    scrubbed = scrub_event(event, {})
    assert scrubbed is not None
    assert "SECRET-7f3a" not in json.dumps(scrubbed)
    assert scrubbed["exception"]["values"][0]["type"] == "IntegrityError"


def test_scrub_event_tolerates_events_without_those_fields() -> None:
    assert scrub_event({}, {}) == {}
    assert scrub_event({"exception": {"values": [{"type": "X"}]}}, {}) == {
        "exception": {"values": [{"type": "X"}]}
    }


def test_the_init_options_are_pinned() -> None:
    kwargs = sentry_init_kwargs(dsn="http://k@localhost:9/1", release="r", environment="e")
    assert kwargs["include_local_variables"] is False
    assert kwargs["max_request_body_size"] == "never"
    assert kwargs["before_send"] is scrub_event
    assert "send_default_pii" not in kwargs  # stays at the SDK default (off), never turned on
    assert kwargs["release"] == "r"
    assert kwargs["environment"] == "e"


def test_main_builds_its_sentry_options_here_and_cannot_reinline_unsafe_ones() -> None:
    # Code-review root cause E: a rule that only lives in a comment gets skipped. A second,
    # hand-written `sentry_sdk.init(dsn=...)` in main.py would silently bypass everything above.
    source = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(encoding="utf-8")
    assert "sentry_init_kwargs(" in source
    calls = [line for line in source.splitlines() if line.strip().startswith("sentry_sdk.init(")]
    assert len(calls) == 1
    assert "sentry_sdk.init(\n        dsn=" not in source

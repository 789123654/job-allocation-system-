"""Pool-utilization warning (db.install_pool_monitor) and the stats it reads (runtime_stats)."""

import json
import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import anyio
import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import QueuePool

import app.core.db as db
from app.core import runtime_stats
from app.core.logging_setup import configure_logging

configure_logging()


def _make_engine(directory: Path) -> Engine:
    return create_engine(
        f"sqlite:///{directory}/pool.db", poolclass=QueuePool, pool_size=2, max_overflow=1
    )


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine]:
    made = _make_engine(tmp_path)
    yield made
    made.dispose()


def _pool_warnings(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    return [r for r in records if r["logger"] == "app.pool"]


def test_silent_below_the_threshold_then_warns_once_when_nearly_full(
    engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    db.install_pool_monitor(engine, capacity=3, warn_ratio=0.7, min_interval_seconds=30.0)
    capsys.readouterr()
    held = [engine.connect(), engine.connect()]  # 2/3 = 0.667 < 0.7
    assert _pool_warnings(capsys) == []

    held.append(engine.connect())  # 3/3 = 1.0
    warnings = _pool_warnings(capsys)
    assert len(warnings) == 1
    assert warnings[0]["level"] == "WARNING"
    assert warnings[0]["event"] == "pool_high_utilization"
    assert (warnings[0]["checked_out"], warnings[0]["capacity"]) == (3, 3)
    assert warnings[0]["utilization"] == 1.0
    for connection in held:
        connection.close()


def test_rate_limited_per_interval_but_not_when_the_interval_is_zero(
    engine: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db.install_pool_monitor(engine, capacity=3, warn_ratio=0.5, min_interval_seconds=3600.0)
    capsys.readouterr()
    first = [engine.connect(), engine.connect()]
    second = engine.connect()  # 3/3 — over threshold, but inside the interval after the 1st warn
    assert len(_pool_warnings(capsys)) == 1
    for connection in [*first, second]:
        connection.close()

    (tmp_path / "b").mkdir()
    unlimited = _make_engine(tmp_path / "b")
    db.install_pool_monitor(unlimited, capacity=3, warn_ratio=0.5, min_interval_seconds=0)
    capsys.readouterr()
    held = [unlimited.connect(), unlimited.connect(), unlimited.connect()]
    assert len(_pool_warnings(capsys)) >= 2  # every checkout at/over 0.5 warns when unrate-limited
    for connection in held:
        connection.close()
    unlimited.dispose()


def test_a_failing_monitor_never_breaks_the_checkout(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("logging is broken")

    db.install_pool_monitor(engine, capacity=1, warn_ratio=0.1, min_interval_seconds=0)
    monkeypatch.setattr(logging.getLogger("app.pool"), "warning", boom)
    connection = engine.connect()  # would raise if the listener's error propagated
    assert connection.closed is False
    connection.close()


def test_stats_read_the_live_engine_and_report_none_for_a_non_queuepool(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db, "engine", engine)
    assert runtime_stats.pool_stats() == (0, 3)
    held = engine.connect()
    assert runtime_stats.pool_stats() == (1, 3)
    held.close()

    monkeypatch.setattr(db, "engine", object())
    assert runtime_stats.pool_stats() == (None, None)


def test_the_semi_public_sqlalchemy_pool_api_we_rely_on_still_exists() -> None:
    """checkedout()/size()/_max_overflow aren't in SQLAlchemy's documented pool API (only status()
    is). If an upgrade renames one, this fails here instead of silently blanking the gauges.
    """
    assert callable(QueuePool.checkedout)
    assert callable(QueuePool.size)
    pool = QueuePool(lambda: None, pool_size=2, max_overflow=1)  # pyright: ignore[reportArgumentType]
    assert pool._max_overflow == 1  # pyright: ignore[reportPrivateUsage]


def test_threadpool_stats_need_an_event_loop_and_degrade_to_none_without_one() -> None:
    assert runtime_stats.threadpool_stats() == (None, None)

    async def inside() -> tuple[int | None, int | None]:
        return runtime_stats.threadpool_stats()

    borrowed, total = anyio.run(inside)
    assert total == 40  # anyio's documented default worker-thread limiter
    assert borrowed is not None
    assert 0 <= borrowed <= total

import asyncio
from types import SimpleNamespace

import pytest

from src.straddle.market_data_worker import collect_once


class FakeStorage:
    def __init__(self):
        self.snapshots = []
        self.heartbeats = []

    def save_snapshot(self, index_price, status, reason=None, pair=None):
        self.snapshots.append((index_price, status, reason, pair))

    def update_heartbeat(self, worker_id, status, details=None):
        self.heartbeats.append((worker_id, status, details))


def test_collect_once_records_no_trade_when_index_is_missing():
    storage = FakeStorage()
    async def fetcher():
        return [], [SimpleNamespace(index_price="0")]

    result = asyncio.run(collect_once(storage, fetcher=fetcher))
    assert result["status"] == "NO_TRADE"
    assert storage.snapshots[0][1] == "NO_TRADE"
    assert storage.heartbeats[-1][1] == "RUNNING"


def test_collect_once_records_selector_no_trade(monkeypatch):
    storage = FakeStorage()

    async def fetcher():
        return [], [SimpleNamespace(index_price="75000")]

    monkeypatch.setattr(
        "src.straddle.market_data_worker.select_best_pair",
        lambda **kwargs: {"status": "NO_TRADE", "reason": "No liquid pair"},
    )
    result = asyncio.run(collect_once(storage, fetcher=fetcher))
    assert result["status"] == "NO_TRADE"
    assert storage.snapshots[0][0] == 75000
    assert storage.snapshots[0][2] == "No liquid pair"


def test_collect_once_marks_heartbeat_error():
    storage = FakeStorage()

    async def fetcher():
        raise RuntimeError("connection failed")

    with pytest.raises(RuntimeError):
        asyncio.run(collect_once(storage, fetcher=fetcher))
    assert storage.heartbeats[-1][1] == "ERROR"
    assert "connection failed" in storage.heartbeats[-1][2]

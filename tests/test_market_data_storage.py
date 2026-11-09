from datetime import date
from types import SimpleNamespace

from src.straddle.market_data_storage import MarketDataStorage


def make_pair():
    return {
        "expiry": date(2026, 11, 13),
        "strike": 75000,
        "settlement": "USDT",
        "call": SimpleNamespace(
            symbol="BTC-13NOV26-75000-C-USDT",
            bid1_price="120",
            ask1_price="125",
            bid1_size="0.1",
            ask1_size="0.2",
        ),
        "put": SimpleNamespace(
            symbol="BTC-13NOV26-75000-P-USDT",
            bid1_price="110",
            ask1_price="115",
            bid1_size="0.3",
            ask1_size="0.4",
        ),
        "combined_entry_bid": 230,
        "combined_buyback_ask": 240,
    }


def test_market_tables_are_created(tmp_path):
    storage = MarketDataStorage(tmp_path / "market.db")
    names = {
        row["name"] for row in storage.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    storage.close()
    assert {"market_snapshots", "selected_pairs", "engine_heartbeat"}.issubset(names)


def test_save_and_read_market_snapshot(tmp_path):
    storage = MarketDataStorage(tmp_path / "market.db")
    snapshot_id = storage.save_snapshot(74822.71, "PAIR_FOUND", pair=make_pair())
    snapshot = storage.connection.execute(
        "SELECT * FROM market_snapshots WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()
    pair = storage.connection.execute(
        "SELECT * FROM selected_pairs WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()
    storage.close()
    assert snapshot["index_price"] == 74822.71
    assert snapshot["status"] == "PAIR_FOUND"
    assert pair["call_symbol"].endswith("-C-USDT")
    assert pair["put_symbol"].endswith("-P-USDT")
    assert pair["combined_entry_bid"] == 230


def test_no_trade_snapshot_does_not_create_pair(tmp_path):
    storage = MarketDataStorage(tmp_path / "market.db")
    snapshot_id = storage.save_snapshot(74822.71, "NO_TRADE", "No liquid pair")
    pair_count = storage.connection.execute(
        "SELECT COUNT(*) FROM selected_pairs WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()[0]
    storage.close()
    assert pair_count == 0


def test_heartbeat_upserts_worker_status(tmp_path):
    storage = MarketDataStorage(tmp_path / "market.db")
    storage.update_heartbeat("worker", "RUNNING", "scan complete")
    first = storage.connection.execute(
        "SELECT * FROM engine_heartbeat WHERE worker_id='worker'"
    ).fetchone()
    storage.update_heartbeat("worker", "STOPPED", "shutdown")
    rows = storage.connection.execute(
        "SELECT * FROM engine_heartbeat WHERE worker_id='worker'"
    ).fetchall()
    storage.close()
    assert len(rows) == 1
    assert first["status"] == "RUNNING"
    assert rows[0]["status"] == "STOPPED"
    assert rows[0]["details"] == "shutdown"

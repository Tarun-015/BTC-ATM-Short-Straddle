from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import sqlite3
import pytest

from src.straddle.market_data_storage import MarketDataStorage
from src.straddle.simulation_service import (
    close_simulation,
    create_simulation,
    get_simulation,
    list_simulations,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "straddle.db"
    storage = MarketDataStorage(path)
    call = SimpleNamespace(
        symbol="BTC-01DEC26-70000-C-USDT",
        bid1_price="10",
        ask1_price="12",
        bid1_size="2",
        ask1_size="2",
    )
    put = SimpleNamespace(
        symbol="BTC-01DEC26-70000-P-USDT",
        bid1_price="8",
        ask1_price="9",
        bid1_size="2",
        ask1_size="2",
    )
    pair = {
        "expiry": date(2026, 12, 1),
        "strike": 70000,
        "settlement": "USDT",
        "call": call,
        "put": put,
        "combined_entry_bid": 18,
        "combined_buyback_ask": 21,
    }
    storage.save_snapshot(70000, "PAIR_FOUND", pair=pair)
    storage.close()
    return path


def test_create_full_simulation_records_both_short_legs(db_path):
    result = create_simulation(db_path, "0.01")

    assert result["trade"]["state"] == "OPEN"
    assert result["trade"]["entry_premium"] == "0.18"
    assert {leg["leg"] for leg in result["legs"]} == {"CALL", "PUT"}
    assert len(result["orders"]) == 2
    assert len(result["events"]) == 2
    assert {order["side"] for order in result["orders"]} == {"SELL"}


def test_create_rejects_invalid_quantity(db_path):
    with pytest.raises(ValueError):
        create_simulation(db_path, "0")


def test_create_rejects_stale_market_snapshot(db_path):
    connection = sqlite3.connect(db_path)
    old = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    connection.execute("UPDATE market_snapshots SET captured_at=?", (old,))
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="stale"):
        create_simulation(db_path)


def test_create_rejects_no_trade_snapshot(db_path):
    connection = sqlite3.connect(db_path)
    connection.execute("UPDATE market_snapshots SET status='NO_TRADE'")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="No eligible"):
        create_simulation(db_path)


def test_single_leg_entry_requires_recovery(db_path):
    result = create_simulation(db_path, "0.01", "CALL_ONLY")

    assert result["trade"]["state"] == "RECOVERY_REQUIRED"
    assert result["trade"]["recovery_required"] == 1
    quantities = {leg["leg"]: leg["entry_filled_quantity"] for leg in result["legs"]}
    assert quantities == {"CALL": "0.01", "PUT": "0"}


def test_partial_both_entry_records_partial_fills(db_path):
    result = create_simulation(db_path, "0.02", "PARTIAL_BOTH")

    assert result["trade"]["state"] == "PARTIALLY_FILLED"
    assert all(leg["entry_filled_quantity"] == "0.01" for leg in result["legs"])


def test_full_exit_closes_both_legs(db_path):
    opened = create_simulation(db_path, "0.01")
    closed = close_simulation(db_path, opened["trade"]["trade_id"])

    assert closed["trade"]["state"] == "CLOSED"
    assert closed["trade"]["recovery_required"] == 0
    assert all(leg["exit_filled_quantity"] == "0.01" for leg in closed["legs"])
    assert len(closed["orders"]) == 4


def test_one_leg_exit_preserves_other_leg_exposure(db_path):
    opened = create_simulation(db_path, "0.01")
    result = close_simulation(db_path, opened["trade"]["trade_id"], "CALL_ONLY")

    assert result["trade"]["state"] == "RECOVERY_REQUIRED"
    quantities = {leg["leg"]: leg["exit_filled_quantity"] for leg in result["legs"]}
    assert quantities == {"CALL": "0.01", "PUT": "0"}


def test_partial_exit_can_be_completed_later(db_path):
    opened = create_simulation(db_path, "0.02")
    partial = close_simulation(db_path, opened["trade"]["trade_id"], "PARTIAL_BOTH")
    assert partial["trade"]["state"] == "RECOVERY_REQUIRED"
    completed = close_simulation(db_path, opened["trade"]["trade_id"], "BOTH_FULL")
    assert completed["trade"]["state"] == "CLOSED"


def test_injected_liquidity_failure_keeps_exposure(db_path):
    opened = create_simulation(db_path, "0.01")
    result = close_simulation(
        db_path,
        opened["trade"]["trade_id"],
        "LIQUIDITY_FAILURE",
    )

    assert result["trade"]["state"] == "RECOVERY_REQUIRED"
    assert result["trade"]["recovery_required"] == 1
    assert len(result["events"]) == 2
    assert all(leg["exit_filled_quantity"] == "0" for leg in result["legs"])


def test_simulations_are_persisted_and_listed(db_path):
    created = create_simulation(db_path)
    trade_id = created["trade"]["trade_id"]

    assert get_simulation(db_path, trade_id)["trade"]["trade_id"] == trade_id
    assert len(list_simulations(db_path)) == 1
    assert len(list_simulations(db_path, include_closed=False)) == 1


def test_actual_insufficient_ask_size_retains_all_exposure(db_path):
    opened = create_simulation(db_path, "0.01")
    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE selected_pairs SET call_ask_size='0.001'"
    )
    connection.commit()
    connection.close()

    result = close_simulation(db_path, opened["trade"]["trade_id"])

    assert result["trade"]["state"] == "RECOVERY_REQUIRED"
    assert all(leg["exit_filled_quantity"] == "0" for leg in result["legs"])
    assert len(result["events"]) == 2


def test_exit_rejects_changed_contract_pair(db_path):
    opened = create_simulation(db_path, "0.01")
    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE selected_pairs SET call_symbol='BTC-01DEC26-71000-C-USDT'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="does not match"):
        close_simulation(db_path, opened["trade"]["trade_id"])

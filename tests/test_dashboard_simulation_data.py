import sqlite3

from dashboard.data_access import load_dashboard_data
from src.straddle.market_data_storage import MarketDataStorage
from src.straddle.simulation_service import initialize_simulation_storage


def test_dashboard_reads_simulation_tables(tmp_path):
    path = tmp_path / "dashboard.db"
    market = MarketDataStorage(path)
    market.close()
    initialize_simulation_storage(path)

    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO simulated_trades (
            trade_id, state, requested_quantity, expiry, strike,
            call_symbol, put_symbol, entry_premium, recovery_required,
            recovery_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "SIM-001", "RECOVERY_REQUIRED", "0.01", "2026-12-01",
            "70000", "CALL", "PUT", "0.18", 1, "test recovery",
            "2026-11-09T10:00:00+00:00", "2026-11-09T10:01:00+00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO simulated_legs (
            trade_id, leg, symbol, state, requested_quantity,
            entry_filled_quantity, exit_filled_quantity
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("SIM-001", "CALL", "CALL", "FILLED", "0.01", "0.01", "0"),
    )
    connection.execute(
        """
        INSERT INTO simulated_orders (
            order_id, trade_id, leg, role, side, status,
            requested_quantity, filled_quantity, price, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "SIM-ORDER-1", "SIM-001", "CALL", "ENTRY", "SELL",
            "FILLED", "0.01", "0.01", "10", "2026-11-09T10:00:00+00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO simulated_events (
            event_id, order_id, trade_id, leg, role, quantity, price, event_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "SIM-EVENT-1", "SIM-ORDER-1", "SIM-001", "CALL",
            "ENTRY", "0.01", "10", "2026-11-09T10:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()

    result = load_dashboard_data(path)

    assert result["available"] is True
    assert result["simulated_trades"][0]["trade_id"] == "SIM-001"
    assert result["simulated_legs"][0]["leg"] == "CALL"
    assert result["simulated_orders"][0]["order_id"] == "SIM-ORDER-1"
    assert result["simulated_events"][0]["event_id"] == "SIM-EVENT-1"


def test_dashboard_supports_database_without_simulation_tables(tmp_path):
    path = tmp_path / "legacy.db"
    MarketDataStorage(path).close()

    result = load_dashboard_data(path)

    assert result["available"] is True
    assert result["simulated_trades"] == []
    assert result["simulated_legs"] == []
    assert result["simulated_orders"] == []
    assert result["simulated_events"] == []

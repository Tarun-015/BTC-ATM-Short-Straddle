import sqlite3

from dashboard.data_access import (
    get_portfolio_metrics,
    get_trade_metrics,
    load_dashboard_data,
)
from src.straddle.storage import SQLiteStorage


def create_database(path):
    storage = SQLiteStorage(path)
    storage.close()

    return path


def insert_sample_trade(path):
    connection = sqlite3.connect(path)

    connection.execute(
        """
        INSERT INTO trades (
            trade_id,
            state,
            requested_quantity,
            recovery_required,
            recovery_reason,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "TRADE-001",
            "OPEN",
            "0.01",
            0,
            None,
            "2026-11-09T10:00:00+00:00",
            "2026-11-09T10:05:00+00:00",
        ),
    )

    connection.executemany(
        """
        INSERT INTO trade_legs (
            trade_id,
            leg,
            state,
            entry_filled_quantity,
            exit_filled_quantity
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("TRADE-001", "CALL", "FILLED", "0.01", "0"),
            ("TRADE-001", "PUT", "FILLED", "0.01", "0"),
        ],
    )

    connection.execute(
        """
        INSERT INTO orders (
            order_id,
            trade_id,
            leg,
            role,
            status,
            requested_quantity,
            filled_quantity,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ORDER-001",
            "TRADE-001",
            "CALL",
            "ENTRY",
            "FILLED",
            "0.01",
            "0.01",
            "2026-11-09T10:01:00+00:00",
        ),
    )

    connection.execute(
        """
        INSERT INTO execution_events (
            event_id,
            order_id,
            trade_id,
            leg,
            role,
            quantity,
            price,
            event_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "EVENT-001",
            "ORDER-001",
            "TRADE-001",
            "CALL",
            "ENTRY",
            "0.01",
            "100",
            "2026-11-09T10:02:00+00:00",
        ),
    )

    connection.commit()
    connection.close()


def test_missing_database_returns_unavailable(tmp_path):
    result = load_dashboard_data(
        tmp_path / "missing.db"
    )

    assert result["available"] is False
    assert result["error"] is not None
    assert result["trades"] == []


def test_empty_database_returns_empty_records(tmp_path):
    path = create_database(
        tmp_path / "empty.db"
    )

    result = load_dashboard_data(path)

    assert result["available"] is True
    assert result["trades"] == []
    assert result["legs"] == []
    assert result["orders"] == []
    assert result["events"] == []


def test_dashboard_loads_all_records(tmp_path):
    path = create_database(
        tmp_path / "sample.db"
    )
    insert_sample_trade(path)

    result = load_dashboard_data(path)

    assert result["available"] is True
    assert len(result["trades"]) == 1
    assert len(result["legs"]) == 2
    assert len(result["orders"]) == 1
    assert len(result["events"]) == 1
    assert result["trades"][0]["trade_id"] == "TRADE-001"


def test_trade_metrics_calculate_exposure(tmp_path):
    path = create_database(
        tmp_path / "metrics.db"
    )
    insert_sample_trade(path)

    data = load_dashboard_data(path)

    metrics = get_trade_metrics(
        "TRADE-001",
        data["legs"],
        data["orders"],
        data["events"],
    )

    assert metrics["entry_filled_quantity"] == 0.02
    assert metrics["exit_filled_quantity"] == 0
    assert metrics["exposed_legs"] == ["CALL", "PUT"]
    assert metrics["order_count"] == 1
    assert metrics["event_count"] == 1


def test_portfolio_metrics_count_trades_and_exposure(tmp_path):
    path = create_database(
        tmp_path / "portfolio.db"
    )
    insert_sample_trade(path)

    data = load_dashboard_data(path)
    metrics = get_portfolio_metrics(data)

    assert metrics["total_trades"] == 1
    assert metrics["open_trades"] == 1
    assert metrics["recovery_trades"] == 0
    assert metrics["trades_with_exposure"] == 1
    assert metrics["total_orders"] == 1
    assert metrics["total_events"] == 1


def test_dashboard_does_not_modify_database(tmp_path):
    path = create_database(
        tmp_path / "readonly.db"
    )
    insert_sample_trade(path)

    connection = sqlite3.connect(path)

    before = connection.execute(
        "SELECT COUNT(*) FROM trades"
    ).fetchone()[0]

    connection.close()

    load_dashboard_data(path)

    connection = sqlite3.connect(path)

    after = connection.execute(
        "SELECT COUNT(*) FROM trades"
    ).fetchone()[0]

    connection.close()

    assert before == after
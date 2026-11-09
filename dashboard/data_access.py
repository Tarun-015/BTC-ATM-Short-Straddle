import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _empty_result(available=False, error=None):
    return {
        "available": available,
        "error": error,
        "trades": [],
        "legs": [],
        "orders": [],
        "events": [],
        "market_snapshot": None,
        "selected_pair": None,
        "heartbeat": None,
        "simulated_trades": [],
        "simulated_legs": [],
        "simulated_orders": [],
        "simulated_events": [],
    }


def _read_table(connection, table, order_by):
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if table not in tables:
        return []
    return [
        dict(row)
        for row in connection.execute(
            f"SELECT * FROM {table} ORDER BY {order_by}"
        ).fetchall()
    ]


def _read_latest_market(connection):
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "market_snapshots" not in tables:
        return None, None
    snapshot = connection.execute(
        "SELECT * FROM market_snapshots ORDER BY snapshot_id DESC LIMIT 1"
    ).fetchone()
    if snapshot is None:
        return None, None
    snapshot = dict(snapshot)
    pair = None
    if "selected_pairs" in tables:
        row = connection.execute(
            "SELECT * FROM selected_pairs WHERE snapshot_id = ?",
            (snapshot["snapshot_id"],),
        ).fetchone()
        pair = dict(row) if row else None
    return snapshot, pair


def load_dashboard_data(db_path):
    path = Path(db_path)
    if not path.exists() or not path.is_file():
        return _empty_result(error=f"Database file not found: {path}")

    connection = None
    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.row_factory = sqlite3.Row
        trades = _read_table(connection, "trades", "updated_at DESC")
        legs = _read_table(connection, "trade_legs", "trade_id, leg")
        orders = _read_table(connection, "orders", "created_at DESC")
        events = _read_table(connection, "execution_events", "event_time DESC")
        market_snapshot, selected_pair = _read_latest_market(connection)
        heartbeat_rows = _read_table(
            connection,
            "engine_heartbeat",
            "last_seen DESC",
        )
        heartbeat = heartbeat_rows[0] if heartbeat_rows else None
        simulated_trades = _read_table(
            connection,
            "simulated_trades",
            "updated_at DESC",
        )
        simulated_legs = _read_table(
            connection,
            "simulated_legs",
            "trade_id, leg",
        )
        simulated_orders = _read_table(
            connection,
            "simulated_orders",
            "created_at DESC",
        )
        simulated_events = _read_table(
            connection,
            "simulated_events",
            "event_time DESC",
        )
        if heartbeat:
            try:
                last_seen = datetime.fromisoformat(heartbeat["last_seen"])
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                age_seconds = max(
                    0,
                    (datetime.now(timezone.utc) - last_seen).total_seconds(),
                )
                heartbeat["age_seconds"] = age_seconds
                heartbeat["effective_status"] = (
                    "STALE"
                    if heartbeat["status"] == "RUNNING" and age_seconds > 20
                    else heartbeat["status"]
                )
            except (TypeError, ValueError):
                heartbeat["age_seconds"] = None
                heartbeat["effective_status"] = "UNKNOWN"
        return {
            "available": True,
            "error": None,
            "trades": trades,
            "legs": legs,
            "orders": orders,
            "events": events,
            "market_snapshot": market_snapshot,
            "selected_pair": selected_pair,
            "heartbeat": heartbeat,
            "simulated_trades": simulated_trades,
            "simulated_legs": simulated_legs,
            "simulated_orders": simulated_orders,
            "simulated_events": simulated_events,
        }
    except (sqlite3.Error, OSError, ValueError) as exc:
        return _empty_result(error=f"Could not read database: {exc}")
    finally:
        if connection is not None:
            connection.close()


def get_trade_metrics(trade_id, legs, orders, events):
    trade_legs = [leg for leg in legs if leg["trade_id"] == trade_id]
    trade_orders = [order for order in orders if order["trade_id"] == trade_id]
    trade_events = [event for event in events if event["trade_id"] == trade_id]
    entry_quantity = sum(float(leg["entry_filled_quantity"]) for leg in trade_legs)
    exit_quantity = sum(float(leg["exit_filled_quantity"]) for leg in trade_legs)
    exposed_legs = [
        leg["leg"] for leg in trade_legs
        if float(leg["entry_filled_quantity"]) > float(leg["exit_filled_quantity"])
    ]
    return {
        "entry_filled_quantity": entry_quantity,
        "exit_filled_quantity": exit_quantity,
        "exposed_legs": exposed_legs,
        "order_count": len(trade_orders),
        "event_count": len(trade_events),
    }


def get_portfolio_metrics(data):
    open_states = {
        "ENTRY_PENDING", "PARTIALLY_FILLED", "OPEN",
        "EXIT_PENDING", "RECOVERY_REQUIRED", "RECOVERY_PENDING",
    }
    open_trades = [trade for trade in data["trades"] if trade["state"] in open_states]
    recovery_trades = [trade for trade in data["trades"] if bool(trade.get("recovery_required", 0))]
    exposed_trade_ids = {
        leg["trade_id"] for leg in data["legs"]
        if float(leg["entry_filled_quantity"]) > float(leg["exit_filled_quantity"])
    }
    return {
        "total_trades": len(data["trades"]),
        "open_trades": len(open_trades),
        "recovery_trades": len(recovery_trades),
        "trades_with_exposure": len(exposed_trade_ids),
        "total_orders": len(data["orders"]),
        "total_events": len(data["events"]),
    }

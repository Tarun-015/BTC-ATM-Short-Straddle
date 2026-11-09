import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4


MAX_MARKET_AGE_SECONDS = 15


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid numeric value: {value}")
    if not result.is_finite():
        raise ValueError(f"Invalid numeric value: {value}")
    return result


def _now():
    return datetime.now(timezone.utc).isoformat()


def _format_decimal(value):
    normalized = value.normalize()
    return format(normalized, "f")


def _connect(db_path):
    path = str(db_path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_simulation_storage(db_path):
    connection = _connect(db_path)
    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS simulated_trades (
                    trade_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    requested_quantity TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    strike TEXT NOT NULL,
                    call_symbol TEXT NOT NULL,
                    put_symbol TEXT NOT NULL,
                    entry_premium TEXT NOT NULL DEFAULT '0',
                    exit_cost TEXT NOT NULL DEFAULT '0',
                    recovery_required INTEGER NOT NULL DEFAULT 0,
                    recovery_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS simulated_legs (
                    trade_id TEXT NOT NULL,
                    leg TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    state TEXT NOT NULL,
                    requested_quantity TEXT NOT NULL,
                    entry_filled_quantity TEXT NOT NULL DEFAULT '0',
                    exit_filled_quantity TEXT NOT NULL DEFAULT '0',
                    entry_price TEXT,
                    exit_price TEXT,
                    PRIMARY KEY (trade_id, leg),
                    FOREIGN KEY (trade_id) REFERENCES simulated_trades(trade_id)
                        ON DELETE CASCADE
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS simulated_orders (
                    order_id TEXT PRIMARY KEY,
                    trade_id TEXT NOT NULL,
                    leg TEXT NOT NULL,
                    role TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_quantity TEXT NOT NULL,
                    filled_quantity TEXT NOT NULL,
                    price TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (trade_id, leg)
                        REFERENCES simulated_legs(trade_id, leg)
                        ON DELETE CASCADE
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS simulated_events (
                    event_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    trade_id TEXT NOT NULL,
                    leg TEXT NOT NULL,
                    role TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    price TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    FOREIGN KEY (order_id) REFERENCES simulated_orders(order_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (trade_id, leg)
                        REFERENCES simulated_legs(trade_id, leg)
                        ON DELETE CASCADE
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_simulated_trades_updated
                ON simulated_trades(updated_at DESC)
            """)
    finally:
        connection.close()


def _latest_pair(connection):
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if not {"market_snapshots", "selected_pairs"}.issubset(tables):
        raise ValueError("Market data tables are not initialized")
    snapshot = connection.execute(
        "SELECT * FROM market_snapshots ORDER BY snapshot_id DESC LIMIT 1"
    ).fetchone()
    if snapshot is None:
        raise ValueError("No market snapshot is available")
    try:
        captured = datetime.fromisoformat(snapshot["captured_at"])
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - captured.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        raise ValueError("Market snapshot timestamp is invalid")
    if age < -2 or age > MAX_MARKET_AGE_SECONDS:
        raise ValueError("Market snapshot is stale or from the future")
    if snapshot["status"] != "PAIR_FOUND":
        raise ValueError("No eligible option pair: " + (snapshot["reason"] or "market scan rejected the pair"))
    pair = connection.execute(
        "SELECT * FROM selected_pairs WHERE snapshot_id = ?",
        (snapshot["snapshot_id"],),
    ).fetchone()
    if pair is None:
        raise ValueError("Selected option pair is missing")
    return dict(snapshot), dict(pair)


def _record_fill(connection, trade_id, leg, role, side, quantity, price):
    order_id = f"SIM-{role}-{uuid4().hex}"
    event_id = f"SIM-EVENT-{uuid4().hex}"
    now = _now()
    connection.execute("""
        INSERT INTO simulated_orders (
            order_id, trade_id, leg, role, side, status,
            requested_quantity, filled_quantity, price, created_at
        ) VALUES (?, ?, ?, ?, ?, 'FILLED', ?, ?, ?, ?)
    """, (
        order_id, trade_id, leg, role, side,
        str(quantity), str(quantity), str(price), now,
    ))
    connection.execute("""
        INSERT INTO simulated_events (
            event_id, order_id, trade_id, leg, role,
            quantity, price, event_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id, order_id, trade_id, leg, role,
        str(quantity), str(price), now,
    ))


def create_simulation(db_path, quantity="0.01", entry_mode="BOTH_FULL"):
    qty = _decimal(quantity)
    if qty <= 0:
        raise ValueError("Quantity must be greater than zero")
    modes = {"BOTH_FULL", "CALL_ONLY", "PUT_ONLY", "PARTIAL_BOTH"}
    if entry_mode not in modes:
        raise ValueError("Unsupported entry simulation mode")
    initialize_simulation_storage(db_path)
    connection = _connect(db_path)
    trade_id = f"SIM-TRADE-{uuid4().hex}"
    now = _now()
    try:
        with connection:
            snapshot, pair = _latest_pair(connection)
            fills = {
                "CALL": qty if entry_mode in ("BOTH_FULL", "CALL_ONLY") else qty / 2 if entry_mode == "PARTIAL_BOTH" else Decimal("0"),
                "PUT": qty if entry_mode in ("BOTH_FULL", "PUT_ONLY") else qty / 2 if entry_mode == "PARTIAL_BOTH" else Decimal("0"),
            }
            prices = {"CALL": _decimal(pair["call_bid"]), "PUT": _decimal(pair["put_bid"])}
            sizes = {"CALL": _decimal(pair["call_bid_size"]), "PUT": _decimal(pair["put_bid_size"])}
            symbols = {"CALL": pair["call_symbol"], "PUT": pair["put_symbol"]}
            for leg in ("CALL", "PUT"):
                if fills[leg] > 0 and (prices[leg] <= 0 or sizes[leg] < fills[leg]):
                    raise ValueError(f"Insufficient bid liquidity for {leg}")
            entry_premium = sum((fills[leg] * prices[leg] for leg in fills), Decimal("0"))
            if entry_mode == "BOTH_FULL":
                state, recovery, reason = "OPEN", 0, None
            elif entry_mode == "PARTIAL_BOTH":
                state, recovery, reason = "PARTIALLY_FILLED", 0, "Both legs have partial simulated entry fills"
            else:
                state, recovery, reason = "RECOVERY_REQUIRED", 1, f"Only {entry_mode.split('_')[0]} leg filled; opposite leg remains unfilled"
            connection.execute("""
                INSERT INTO simulated_trades (
                    trade_id, state, requested_quantity, expiry, strike,
                    call_symbol, put_symbol, entry_premium, recovery_required,
                    recovery_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_id, state, str(qty), pair["expiry"], str(pair["strike"]),
                symbols["CALL"], symbols["PUT"], _format_decimal(entry_premium),
                recovery, reason, now, now,
            ))
            for leg in ("CALL", "PUT"):
                leg_state = "FILLED" if fills[leg] == qty else "PARTIALLY_FILLED" if fills[leg] > 0 else "PENDING"
                connection.execute("""
                    INSERT INTO simulated_legs (
                        trade_id, leg, symbol, state, requested_quantity,
                        entry_filled_quantity, entry_price
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_id, leg, symbols[leg], leg_state, str(qty),
                    str(fills[leg]), str(prices[leg]) if fills[leg] > 0 else None,
                ))
                if fills[leg] > 0:
                    _record_fill(connection, trade_id, leg, "ENTRY", "SELL", fills[leg], prices[leg])
        return get_simulation(db_path, trade_id)
    finally:
        connection.close()


def close_simulation(db_path, trade_id, close_mode="BOTH_FULL"):
    modes = {"BOTH_FULL", "CALL_ONLY", "PUT_ONLY", "PARTIAL_BOTH", "LIQUIDITY_FAILURE"}
    if close_mode not in modes:
        raise ValueError("Unsupported exit simulation mode")
    initialize_simulation_storage(db_path)
    connection = _connect(db_path)
    try:
        with connection:
            trade = connection.execute(
                "SELECT * FROM simulated_trades WHERE trade_id = ?", (trade_id,)
            ).fetchone()
            if trade is None:
                raise ValueError("Simulation trade was not found")
            if trade["state"] == "CLOSED":
                raise ValueError("Simulation trade is already closed")
            if close_mode == "LIQUIDITY_FAILURE":
                connection.execute("""
                    UPDATE simulated_trades SET state='RECOVERY_REQUIRED',
                    recovery_required=1, recovery_reason=?, updated_at=?
                    WHERE trade_id=?
                """, ("Injected insufficient-liquidity scenario; no exit fill recorded", _now(), trade_id))
            else:
                snapshot, pair = _latest_pair(connection)
                if pair["call_symbol"] != trade["call_symbol"] or pair["put_symbol"] != trade["put_symbol"]:
                    raise ValueError("Latest market pair does not match the simulated trade contracts")
                legs = connection.execute(
                    "SELECT * FROM simulated_legs WHERE trade_id = ? ORDER BY leg", (trade_id,)
                ).fetchall()
                remaining = {
                    row["leg"]: _decimal(row["entry_filled_quantity"]) - _decimal(row["exit_filled_quantity"])
                    for row in legs
                }
                asks = {"CALL": _decimal(pair["call_ask"]), "PUT": _decimal(pair["put_ask"])}
                ask_sizes = {"CALL": _decimal(pair["call_ask_size"]), "PUT": _decimal(pair["put_ask_size"])}
                close_quantities = {}
                for leg in ("CALL", "PUT"):
                    amount = remaining[leg]
                    if close_mode == "CALL_ONLY" and leg != "CALL":
                        amount = Decimal("0")
                    elif close_mode == "PUT_ONLY" and leg != "PUT":
                        amount = Decimal("0")
                    elif close_mode == "PARTIAL_BOTH":
                        amount = amount / 2
                    close_quantities[leg] = amount
                insufficient_leg = next((
                    leg for leg, amount in close_quantities.items()
                    if amount > 0 and (asks[leg] <= 0 or ask_sizes[leg] < amount)
                ), None)
                if insufficient_leg:
                    connection.execute("""
                        UPDATE simulated_trades SET state='RECOVERY_REQUIRED',
                        recovery_required=1, recovery_reason=?, updated_at=?
                        WHERE trade_id=?
                    """, (f"Insufficient current ask liquidity to close {insufficient_leg}; exposure retained", _now(), trade_id))
                else:
                    exit_cost = Decimal("0")
                    for leg, amount in close_quantities.items():
                        if amount <= 0:
                            continue
                        _record_fill(connection, trade_id, leg, "EXIT", "BUY", amount, asks[leg])
                        old = connection.execute(
                            "SELECT exit_filled_quantity FROM simulated_legs WHERE trade_id=? AND leg=?",
                            (trade_id, leg),
                        ).fetchone()
                        new_exit = _decimal(old["exit_filled_quantity"]) + amount
                        entry_quantity = next(
                            _decimal(row["entry_filled_quantity"])
                            for row in legs if row["leg"] == leg
                        )
                        connection.execute("""
                            UPDATE simulated_legs SET exit_filled_quantity=?, exit_price=?, state=?
                            WHERE trade_id=? AND leg=?
                        """, (
                            str(new_exit), str(asks[leg]),
                            "CLOSED" if new_exit == entry_quantity else "EXIT_PARTIAL",
                            trade_id, leg,
                        ))
                        exit_cost += amount * asks[leg]
                    refreshed = connection.execute(
                        "SELECT * FROM simulated_legs WHERE trade_id=?", (trade_id,)
                    ).fetchall()
                    exposure = sum((
                        _decimal(row["entry_filled_quantity"]) - _decimal(row["exit_filled_quantity"])
                        for row in refreshed
                    ), Decimal("0"))
                    total_exit = _decimal(trade["exit_cost"]) + exit_cost
                    if exposure == 0:
                        state, recovery, reason = "CLOSED", 0, None
                    else:
                        state, recovery, reason = "RECOVERY_REQUIRED", 1, "Simulated exit left outstanding leg exposure"
                    connection.execute("""
                        UPDATE simulated_trades SET state=?, exit_cost=?, recovery_required=?,
                        recovery_reason=?, updated_at=? WHERE trade_id=?
                    """, (state, str(total_exit), recovery, reason, _now(), trade_id))
        return get_simulation(db_path, trade_id)
    finally:
        connection.close()


def get_simulation(db_path, trade_id):
    initialize_simulation_storage(db_path)
    connection = _connect(db_path)
    try:
        trade = connection.execute(
            "SELECT * FROM simulated_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
        if trade is None:
            return None
        legs = connection.execute(
            "SELECT * FROM simulated_legs WHERE trade_id = ? ORDER BY leg", (trade_id,)
        ).fetchall()
        orders = connection.execute(
            "SELECT * FROM simulated_orders WHERE trade_id = ? ORDER BY created_at", (trade_id,)
        ).fetchall()
        events = connection.execute(
            "SELECT * FROM simulated_events WHERE trade_id = ? ORDER BY event_time", (trade_id,)
        ).fetchall()
        return {
            "trade": dict(trade),
            "legs": [dict(row) for row in legs],
            "orders": [dict(row) for row in orders],
            "events": [dict(row) for row in events],
        }
    finally:
        connection.close()


def list_simulations(db_path, include_closed=True):
    initialize_simulation_storage(db_path)
    connection = _connect(db_path)
    try:
        query = "SELECT * FROM simulated_trades"
        if not include_closed:
            query += " WHERE state != 'CLOSED'"
        query += " ORDER BY created_at DESC"
        return [dict(row) for row in connection.execute(query).fetchall()]
    finally:
        connection.close()

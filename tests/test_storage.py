
from decimal import Decimal
from types import SimpleNamespace
import sqlite3

import pytest

from src.straddle.storage import SQLiteStorage


@pytest.fixture
def storage():
    db = SQLiteStorage(":memory:")
    db.initialize()

    yield db

    db.close()


def make_trade():
    return SimpleNamespace(
        trade_id="TRADE-001",
        state="OPEN",
        requested_quantity=Decimal("0.01"),
        legs={
            "CALL": "FILLED",
            "PUT": "PARTIALLY_FILLED",
        },
        filled_quantities={
            "CALL": Decimal("0.01"),
            "PUT": Decimal("0.005"),
        },
        exit_filled_quantities={
            "CALL": Decimal("0"),
            "PUT": Decimal("0"),
        },
    )


def make_order():
    return {
        "order_id": "ORDER-001",
        "trade_id": "TRADE-001",
        "leg": "CALL",
        "role": "ENTRY",
        "status": "FILLED",
        "requested_quantity": "0.01",
        "filled_quantity": "0.01",
    }


def make_event():
    return {
        "event_id": "EVENT-001",
        "order_id": "ORDER-001",
        "trade_id": "TRADE-001",
        "leg": "CALL",
        "role": "ENTRY",
        "quantity": "0.01",
        "price": "1250.50",
        "event_time": "2026-11-09T10:00:00+00:00",
    }


def prepare_trade_and_order(storage):
    storage.save_trade(make_trade())
    storage.save_order(make_order())


def test_database_initializes(storage):
    tables = storage.connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        """
    ).fetchall()

    table_names = {row["name"] for row in tables}

    assert {
        "trades",
        "trade_legs",
        "orders",
        "execution_events",
    }.issubset(table_names)


def test_database_initialization_is_idempotent(storage):
    storage.initialize()

    result = storage.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
    ).fetchone()

    assert result[0] >= 4


def test_foreign_keys_are_enabled(storage):
    result = storage.connection.execute(
        "PRAGMA foreign_keys"
    ).fetchone()

    assert result[0] == 1


def test_trade_id_is_primary_key(storage):
    columns = storage.connection.execute(
        "PRAGMA table_info(trades)"
    ).fetchall()

    primary_keys = [
        column["name"]
        for column in columns
        if column["pk"] == 1
    ]

    assert primary_keys == ["trade_id"]


def test_execution_event_id_is_primary_key(storage):
    columns = storage.connection.execute(
        "PRAGMA table_info(execution_events)"
    ).fetchall()

    primary_keys = [
        column["name"]
        for column in columns
        if column["pk"] == 1
    ]

    assert primary_keys == ["event_id"]


def test_save_and_retrieve_trade(storage):
    storage.save_trade(make_trade())

    saved = storage.get_trade("TRADE-001")

    assert saved["trade_id"] == "TRADE-001"
    assert saved["state"] == "OPEN"
    assert saved["requested_quantity"] == "0.01"


def test_save_call_and_put_legs(storage):
    storage.save_trade(make_trade())

    legs = storage.get_trade_legs("TRADE-001")
    saved_legs = {leg["leg"]: leg for leg in legs}

    assert saved_legs["CALL"]["state"] == "FILLED"
    assert saved_legs["CALL"]["entry_filled_quantity"] == "0.01"

    assert saved_legs["PUT"]["state"] == "PARTIALLY_FILLED"
    assert saved_legs["PUT"]["entry_filled_quantity"] == "0.005"


def test_saving_trade_again_updates_existing_record(storage):
    trade = make_trade()
    storage.save_trade(trade)

    trade.state = "EXIT_PENDING"
    trade.legs["CALL"] = "EXIT_PENDING"
    trade.exit_filled_quantities["CALL"] = Decimal("0.01")

    storage.save_trade(trade)

    saved = storage.get_trade("TRADE-001")
    legs = storage.get_trade_legs("TRADE-001")
    saved_call = next(
        leg for leg in legs if leg["leg"] == "CALL"
    )

    assert saved["state"] == "EXIT_PENDING"
    assert saved_call["state"] == "EXIT_PENDING"
    assert saved_call["exit_filled_quantity"] == "0.01"

    count = storage.connection.execute(
        "SELECT COUNT(*) FROM trades WHERE trade_id = ?",
        ("TRADE-001",),
    ).fetchone()[0]

    assert count == 1


def test_missing_trade_returns_none(storage):
    assert storage.get_trade("UNKNOWN") is None
    assert storage.get_trade_legs("UNKNOWN") == []


def test_save_and_retrieve_order(storage):
    prepare_trade_and_order(storage)

    orders = storage.get_orders("TRADE-001")

    assert len(orders) == 1
    assert orders[0]["order_id"] == "ORDER-001"
    assert orders[0]["role"] == "ENTRY"
    assert orders[0]["status"] == "FILLED"
    assert orders[0]["filled_quantity"] == "0.01"


def test_saving_order_again_updates_existing_order(storage):
    prepare_trade_and_order(storage)

    order = make_order()
    order["status"] = "CANCELLED"
    order["filled_quantity"] = "0.005"

    storage.save_order(order)

    orders = storage.get_orders("TRADE-001")

    assert len(orders) == 1
    assert orders[0]["status"] == "CANCELLED"
    assert orders[0]["filled_quantity"] == "0.005"


def test_order_requires_existing_trade(storage):
    with pytest.raises(sqlite3.IntegrityError):
        storage.save_order(make_order())


def test_save_execution_event(storage):
    prepare_trade_and_order(storage)

    inserted = storage.save_execution_event(make_event())

    assert inserted is True

    events = storage.get_execution_events("TRADE-001")

    assert len(events) == 1
    assert events[0]["event_id"] == "EVENT-001"
    assert events[0]["price"] == "1250.50"
    assert events[0]["quantity"] == "0.01"


def test_duplicate_execution_event_is_ignored(storage):
    prepare_trade_and_order(storage)

    first = storage.save_execution_event(make_event())
    second = storage.save_execution_event(make_event())

    assert first is True
    assert second is False

    events = storage.get_execution_events("TRADE-001")
    assert len(events) == 1


def test_execution_event_requires_existing_order(storage):
    storage.save_trade(make_trade())

    with pytest.raises(sqlite3.IntegrityError):
        storage.save_execution_event(make_event())


def test_load_complete_trade_snapshot(storage):
    prepare_trade_and_order(storage)
    storage.save_execution_event(make_event())

    snapshot = storage.load_trade_snapshot("TRADE-001")

    assert snapshot is not None
    assert snapshot["trade"]["trade_id"] == "TRADE-001"
    assert len(snapshot["legs"]) == 2
    assert len(snapshot["orders"]) == 1
    assert len(snapshot["execution_events"]) == 1


def test_missing_snapshot_returns_none(storage):
    assert storage.load_trade_snapshot("UNKNOWN") is None


def test_trade_deletion_cascades_to_child_records(storage):
    prepare_trade_and_order(storage)
    storage.save_execution_event(make_event())

    with storage.connection:
        storage.connection.execute(
            "DELETE FROM trades WHERE trade_id = ?",
            ("TRADE-001",),
        )

    assert storage.get_trade("TRADE-001") is None
    assert storage.get_trade_legs("TRADE-001") == []
    assert storage.get_orders("TRADE-001") == []
    assert storage.get_execution_events("TRADE-001") == []

def test_data_survives_database_restart(tmp_path):
    db_path = tmp_path / "restart_test.db"

    first_storage = SQLiteStorage(db_path)
    first_storage.initialize()
    first_storage.save_trade(make_trade())
    first_storage.close()

    second_storage = SQLiteStorage(db_path)
    second_storage.initialize()

    saved = second_storage.load_trade_snapshot("TRADE-001")

    assert saved is not None
    assert saved["trade"]["state"] == "OPEN"
    assert len(saved["legs"]) == 2

    second_storage.close()


def test_save_trade_manager_saves_orders_and_events(storage):
    prepare_trade_and_order(storage)

    manager = make_trade()
    manager.orders = {"ORDER-001": make_order()}
    manager.execution_events = [make_event()]

    storage.save_trade_manager(manager)

    snapshot = storage.load_trade_snapshot("TRADE-001")

    assert len(snapshot["orders"]) == 1
    assert len(snapshot["execution_events"]) == 1
    

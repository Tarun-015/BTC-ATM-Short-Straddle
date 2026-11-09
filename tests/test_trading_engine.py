import asyncio
from types import SimpleNamespace

from src.straddle.trading_engine import TradingEngine
from src.straddle.storage import SQLiteStorage
from src.straddle.trade_manager import TradeManager


def make_ticker(
    symbol,
    bid,
    ask,
    bid_size="1",
    ask_size="1",
):
    return SimpleNamespace(
        symbol=symbol,
        bid1_price=str(bid),
        ask1_price=str(ask),
        bid1_size=str(bid_size),
        ask1_size=str(ask_size),
    )


def make_stable_result(
    call_ask="10.05",
    put_ask="10.05",
    call_ask_size="1",
    put_ask_size="1",
    call_symbol="BTC-01JAN27-75000-C-USDT",
    put_symbol="BTC-01JAN27-75000-P-USDT",
):
    call = make_ticker(
        call_symbol, "10", call_ask,
        ask_size=call_ask_size,
    )
    put = make_ticker(
        put_symbol, "10", put_ask,
        ask_size=put_ask_size,
    )

    instrument = SimpleNamespace(multiplier="1")

    return {
        "status": "STABLE_PAIR",
        "pair": {
            "call": call,
            "put": put,
            "call_instrument": instrument,
            "put_instrument": instrument,
        },
        "stable_snapshots": 3,
        "index_price": 75000,
    }


def make_engine(tmp_path, stable_result=None):
    stable_result = stable_result or make_stable_result()

    async def fake_scanner(required_quantity):
        return {"status": "PAIR_FOUND"}

    async def fake_quote_monitor(
        required_quantity,
        required_snapshots,
        interval_seconds,
    ):
        return stable_result

    storage = SQLiteStorage(tmp_path / "engine.db")

    return TradingEngine(
        quantity=0.01,
        required_snapshots=3,
        interval_seconds=0,
        scanner_fn=fake_scanner,
        quote_monitor_fn=fake_quote_monitor,
        storage=storage,
    )


def test_engine_completes_entry_and_persists_trade(tmp_path):
    engine = make_engine(tmp_path)

    try:
        result = asyncio.run(engine.run_once())

        assert result["status"] == "CYCLE_COMPLETED"
        assert result["execution_mode"] == "SIMULATION_ONLY"
        assert result["trade_state"] == "OPEN"
        assert result["position"]["risk_action"] == "HOLD"

        snapshot = result["database_snapshot"]

        assert snapshot["trade"]["state"] == "OPEN"
        assert len(snapshot["legs"]) == 2
        assert len(snapshot["orders"]) == 2
        assert len(snapshot["execution_events"]) == 2
        assert {o["role"] for o in snapshot["orders"]} == {"ENTRY"}

    finally:
        engine.close()


def test_engine_simulates_exit_when_stop_loss_triggers(tmp_path):
    engine = make_engine(
        tmp_path,
        make_stable_result("10.20", "10.20"),
    )

    try:
        result = asyncio.run(engine.run_once())

        assert result["status"] == "CYCLE_COMPLETED"
        assert result["position"]["risk_action"] == "STOP_LOSS"
        assert result["trade_state"] == "CLOSED"
        assert result["exit_state"] == "CLOSED"
        assert result["recovery_required"] is False

        snapshot = result["database_snapshot"]

        assert len(snapshot["orders"]) == 4
        assert len(snapshot["execution_events"]) == 4
        assert {o["role"] for o in snapshot["orders"]} == {
            "ENTRY", "EXIT"
        }
        assert all(
            leg["state"] == "CLOSED"
            for leg in snapshot["legs"]
        )

    finally:
        engine.close()


def test_engine_stops_when_market_scan_finds_no_pair(tmp_path):
    async def no_pair_scanner(required_quantity):
        return {
            "status": "NO_TRADE",
            "reason": "No liquid pair",
        }

    storage = SQLiteStorage(tmp_path / "no_pair.db")

    engine = TradingEngine(
        storage=storage,
        scanner_fn=no_pair_scanner,
        quantity=0.01,
    )

    try:
        result = asyncio.run(engine.run_once())

        assert result["status"] == "NO_TRADE"
        assert result["stage"] == "MARKET_SCAN"
        assert result["reason"] == "No liquid pair"
        assert engine.active_trade is None

    finally:
        engine.close()


def test_engine_stops_when_entry_quotes_are_not_stable(tmp_path):
    async def fake_scanner(required_quantity):
        return {"status": "PAIR_FOUND"}

    async def unstable_monitor(
        required_quantity,
        required_snapshots,
        interval_seconds,
    ):
        return {
            "status": "NO_STABLE_PAIR",
            "stable_snapshots": 1,
        }

    storage = SQLiteStorage(tmp_path / "unstable.db")

    engine = TradingEngine(
        storage=storage,
        scanner_fn=fake_scanner,
        quote_monitor_fn=unstable_monitor,
        quantity=0.01,
    )

    try:
        result = asyncio.run(engine.run_once())

        assert result["status"] == "NO_TRADE"
        assert result["stage"] == "QUOTE_MONITOR"
        assert engine.active_trade is None

    finally:
        engine.close()


def test_recovery_inspection_never_resumes_trade(tmp_path):
    storage = SQLiteStorage(tmp_path / "recovery.db")
    engine = TradingEngine(storage=storage)

    try:
        trade = TradeManager("RECOVERY-TEST")
        trade.start_entry()
        engine.storage.save_trade(trade)

        result = engine.inspect_recovery("RECOVERY-TEST")

        assert result["status"] == "RECOVERY_REVIEW_REQUIRED"
        assert result["automatic_resume"] is False
        assert result["exchange_reconciliation"] is False

    finally:
        engine.close()


def test_recovery_inspection_handles_missing_trade(tmp_path):
    storage = SQLiteStorage(tmp_path / "missing.db")
    engine = TradingEngine(storage=storage)

    try:
        result = engine.inspect_recovery("DOES-NOT-EXIST")
        assert result["status"] == "NOT_FOUND"

    finally:
        engine.close()


def test_fresh_quotes_are_requested_after_entry(tmp_path):
    calls = {"count": 0}

    async def scanner(required_quantity):
        return {"status": "PAIR_FOUND"}

    async def quote_monitor(
        required_quantity,
        required_snapshots,
        interval_seconds,
    ):
        calls["count"] += 1
        return make_stable_result()

    storage = SQLiteStorage(tmp_path / "fresh.db")

    engine = TradingEngine(
        storage=storage,
        scanner_fn=scanner,
        quote_monitor_fn=quote_monitor,
        quantity=0.01,
        interval_seconds=0,
    )

    try:
        result = asyncio.run(engine.run_once())

        assert result["status"] == "CYCLE_COMPLETED"
        assert calls["count"] == 2

    finally:
        engine.close()


def test_changed_contract_pair_blocks_risk_evaluation(tmp_path):
    calls = {"count": 0}

    async def scanner(required_quantity):
        return {"status": "PAIR_FOUND"}

    async def quote_monitor(
        required_quantity,
        required_snapshots,
        interval_seconds,
    ):
        calls["count"] += 1

        if calls["count"] == 1:
            return make_stable_result()

        return make_stable_result(
            call_symbol="BTC-01JAN27-76000-C-USDT",
            put_symbol="BTC-01JAN27-76000-P-USDT",
        )

    storage = SQLiteStorage(tmp_path / "changed_pair.db")

    engine = TradingEngine(
        storage=storage,
        scanner_fn=scanner,
        quote_monitor_fn=quote_monitor,
        quantity=0.01,
        interval_seconds=0,
    )

    try:
        result = asyncio.run(engine.run_once())

        assert result["position"]["risk_action"] == "QUOTE_PAIR_CHANGED"
        assert result["trade_state"] == "OPEN"
        assert result["exit_state"] is None

    finally:
        engine.close()


def test_unavailable_fresh_quotes_do_not_trigger_exit(tmp_path):
    calls = {"count": 0}

    async def scanner(required_quantity):
        return {"status": "PAIR_FOUND"}

    async def quote_monitor(
        required_quantity,
        required_snapshots,
        interval_seconds,
    ):
        calls["count"] += 1

        if calls["count"] == 1:
            return make_stable_result()

        return {
            "status": "NO_STABLE_PAIR",
            "stable_snapshots": 0,
        }

    storage = SQLiteStorage(tmp_path / "no_fresh_quotes.db")

    engine = TradingEngine(
        storage=storage,
        scanner_fn=scanner,
        quote_monitor_fn=quote_monitor,
        quantity=0.01,
        interval_seconds=0,
    )

    try:
        result = asyncio.run(engine.run_once())

        assert result["position"]["risk_action"] == "QUOTE_UNAVAILABLE"
        assert result["trade_state"] == "OPEN"
        assert result["exit_state"] is None

    finally:
        engine.close()


def test_failed_exit_preserves_exposure_and_persists_recovery(tmp_path):
    engine = make_engine(
        tmp_path,
        make_stable_result(
            call_ask="10.20",
            put_ask="10.20",
            call_ask_size="0.001",
            put_ask_size="0.001",
        ),
    )

    try:
        result = asyncio.run(engine.run_once())

        assert result["position"]["risk_action"] == "STOP_LOSS"
        assert result["exit_state"] == "RECOVERY_REQUIRED"
        assert result["trade_state"] == "EXIT_PENDING"
        assert result["recovery_required"] is True
        assert result["recovery_reason"] is not None

        snapshot = result["database_snapshot"]

        assert snapshot["trade"]["recovery_required"] == 1
        assert snapshot["trade"]["recovery_reason"] is not None

        assert all(
            leg["entry_filled_quantity"] == "0.01"
            for leg in snapshot["legs"]
        )

        assert all(
            leg["exit_filled_quantity"] == "0"
            for leg in snapshot["legs"]
        )

        recovery = engine.inspect_recovery(result["trade_id"])

        assert recovery["status"] == "RECOVERY_REVIEW_REQUIRED"
        assert recovery["recovery_required"] is True
        assert set(recovery["exposed_legs"]) == {"CALL", "PUT"}
        assert recovery["automatic_resume"] is False

    finally:
        engine.close()
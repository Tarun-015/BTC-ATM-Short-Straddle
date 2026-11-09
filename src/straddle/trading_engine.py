import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from src.straddle.market_scanner import scan_market
from src.straddle.quote_monitor import monitor_quotes
from src.straddle.simulated_executor import simulate_short_straddle_entry
from src.straddle.position_monitor import monitor_position
from src.straddle.trade_manager import TradeManager
from src.straddle.storage import SQLiteStorage


class TradingEngine:
    """One-cycle BTC short-straddle paper-trading orchestrator."""

    EXECUTION_MODE = "SIMULATION_ONLY"

    def __init__(
        self,
        db_path="data/straddle.db",
        quantity=0.01,
        required_snapshots=3,
        interval_seconds=2,
        scanner_fn=None,
        quote_monitor_fn=None,
        executor_fn=None,
        position_monitor_fn=None,
        storage=None,
    ):
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if required_snapshots < 1:
            raise ValueError("At least one snapshot is required")
        if interval_seconds < 0:
            raise ValueError("Interval cannot be negative")

        self.quantity = quantity
        self.required_snapshots = required_snapshots
        self.interval_seconds = interval_seconds

        self.scanner_fn = scanner_fn or scan_market
        self.quote_monitor_fn = quote_monitor_fn or monitor_quotes
        self.executor_fn = executor_fn or simulate_short_straddle_entry
        self.position_monitor_fn = position_monitor_fn or monitor_position

        self.storage = storage or SQLiteStorage(db_path)
        self.storage.initialize()
        self.active_trade = None

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _new_id(prefix):
        return f"{prefix}-{uuid4().hex}"

    @staticmethod
    def _decimal(value):
        from decimal import Decimal, InvalidOperation

        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"Invalid decimal value: {value}")

        if not result.is_finite():
            raise ValueError(f"Non-finite decimal value: {value}")

        return result

    def _persist(self, trade):
        """Persist trade state, normalized orders and priced fill events."""
        self.storage.save_trade(trade)

        for order_id, order in trade.orders.items():
            leg = order["leg"]
            role = order["role"]

            requested_quantity = (
                trade.requested_quantity
                if role == "ENTRY"
                else trade.filled_quantities[leg]
            )

            self.storage.save_order({
                "order_id": order_id,
                "trade_id": trade.trade_id,
                "leg": leg,
                "role": role,
                "status": order["status"],
                "requested_quantity": str(requested_quantity),
                "filled_quantity": str(order["filled_quantity"]),
                "created_at": self._now(),
            })

        for event in trade.execution_events:
            if event.get("type") != "EXECUTION":
                continue
            if event.get("price") is None:
                continue

            self.storage.save_execution_event({
                "event_id": event["event_id"],
                "order_id": event["order_id"],
                "trade_id": trade.trade_id,
                "leg": event["leg"],
                "role": event["role"],
                "quantity": str(event["quantity"]),
                "price": str(event["price"]),
                "event_time": self._now(),
            })

    def _record_fill(self, trade, leg, role, quantity, price):
        order_id = self._new_id(role)

        if not trade.register_order(leg, role, order_id):
            raise RuntimeError(
                f"Could not register {role} order for {leg}"
            )

        self._persist(trade)

        if not trade.record_execution_event(
            order_id=order_id,
            event_id=self._new_id("EXEC"),
            fill_quantity=quantity,
            price=price,
        ):
            raise RuntimeError(
                f"Could not record {role} fill for {leg}"
            )

        self._persist(trade)
        return order_id

    @staticmethod
    def _same_contract_pair(first_pair, second_pair):
        """Ensure fresh quotes refer to exactly the original contracts."""
        try:
            return (
                first_pair["call"].symbol == second_pair["call"].symbol
                and first_pair["put"].symbol == second_pair["put"].symbol
            )
        except (KeyError, AttributeError, TypeError):
            return False

    @staticmethod
    def _calculate_buyback_cost(pair, quantity):
        """Calculate buyback cost from ask prices and contract multipliers."""
        qty = TradingEngine._decimal(quantity)

        call_ask = TradingEngine._decimal(pair["call"].ask1_price)
        put_ask = TradingEngine._decimal(pair["put"].ask1_price)

        call_multiplier = TradingEngine._decimal(
            pair["call_instrument"].multiplier
        )
        put_multiplier = TradingEngine._decimal(
            pair["put_instrument"].multiplier
        )

        if qty <= 0 or call_ask <= 0 or put_ask <= 0:
            raise ValueError("Invalid buyback quantity or ask price")

        if call_multiplier <= 0 or put_multiplier <= 0:
            raise ValueError("Invalid contract multiplier")

        if call_multiplier != put_multiplier:
            raise ValueError("Call and Put multipliers differ")

        return (
            call_ask * qty * call_multiplier
            + put_ask * qty * put_multiplier
        )

    def _mark_recovery(self, trade, reason):
        """Persist recovery information without claiming exposure is closed."""
        trade.mark_recovery_required(reason)

        for leg in ("CALL", "PUT"):
            if (
                trade.legs[leg].value == "EXIT_PENDING"
                and trade.can_retry_exit(leg)
            ):
                trade.record_exit_failure(leg)

        self._persist(trade)

    def _simulate_exit(self, trade, pair):
        """
        Simulate each buyback independently.

        If one leg fails, already closed legs remain closed and all
        remaining exposure stays recorded for manual recovery.
        """
        if not trade.request_exit():
            raise RuntimeError("Trade is not eligible for normal exit")

        self._persist(trade)

        for leg in ("CALL", "PUT"):
            ticker = pair["call"] if leg == "CALL" else pair["put"]
            instrument = (
                pair["call_instrument"]
                if leg == "CALL"
                else pair["put_instrument"]
            )

            remaining = trade.remaining_exposure(leg)

            if remaining <= 0:
                continue

            ask = self._decimal(ticker.ask1_price)
            ask_size = self._decimal(ticker.ask1_size)
            multiplier = self._decimal(instrument.multiplier)

            if ask <= 0:
                raise RuntimeError(f"Invalid ask price for {leg}")

            if ask_size < remaining:
                raise RuntimeError(
                    f"Insufficient ask liquidity to exit {leg}"
                )

            if multiplier <= 0:
                raise RuntimeError(f"Invalid multiplier for {leg}")

            self._record_fill(
                trade,
                leg,
                "EXIT",
                remaining,
                ask,
            )

        self._persist(trade)

        if trade.state.value != "CLOSED":
            raise RuntimeError(
                "Exit did not close all trade exposure"
            )

        return "CLOSED"

    async def run_once(self):
        """Run one market scan, entry, fresh risk check and optional exit."""
        if self.active_trade is not None and self.active_trade.state.value not in (
            "CLOSED",
            "FAILED",
        ):
            return {
                "status": "BLOCKED",
                "reason": "An unfinished trade is already active",
                "trade_id": self.active_trade.trade_id,
            }

        market_result = await self.scanner_fn(
            required_quantity=self.quantity
        )

        if market_result.get("status") != "PAIR_FOUND":
            return {
                "status": "NO_TRADE",
                "stage": "MARKET_SCAN",
                "reason": market_result.get(
                    "reason",
                    "No eligible Call-Put pair",
                ),
            }

        entry_quotes = await self.quote_monitor_fn(
            required_quantity=self.quantity,
            required_snapshots=self.required_snapshots,
            interval_seconds=self.interval_seconds,
        )

        if entry_quotes.get("status") != "STABLE_PAIR":
            return {
                "status": "NO_TRADE",
                "stage": "QUOTE_MONITOR",
                "reason": entry_quotes.get(
                    "reason",
                    "No stable entry pair",
                ),
            }

        execution = self.executor_fn(
            stable_result=entry_quotes,
            quantity=self.quantity,
        )

        if execution.get("status") != "SIMULATED_FILLED":
            return {
                "status": "ENTRY_REJECTED",
                "stage": "SIMULATED_EXECUTION",
                "reason": execution.get(
                    "reason",
                    "Simulated entry was rejected",
                ),
            }

        trade = TradeManager(
            trade_id=self._new_id("BTC-STRADDLE"),
            requested_quantity=self._decimal(self.quantity),
        )
        self.active_trade = trade

        if not trade.start_entry():
            raise RuntimeError("Could not start trade entry")

        self._persist(trade)

        try:
            self._record_fill(
                trade,
                "CALL",
                "ENTRY",
                execution["call"]["quantity"],
                execution["call"]["simulated_fill_price"],
            )

            self._record_fill(
                trade,
                "PUT",
                "ENTRY",
                execution["put"]["quantity"],
                execution["put"]["simulated_fill_price"],
            )
        except Exception as exc:
            self._mark_recovery(
                trade,
                f"Entry recording failure: {exc}",
            )
            return {
                "status": "ENTRY_RECOVERY_REQUIRED",
                "trade_id": trade.trade_id,
                "trade_state": trade.state.value,
                "recovery_required": True,
                "recovery_reason": trade.recovery_reason,
            }

        if trade.state.value != "OPEN":
            self._persist(trade)
            return {
                "status": "ENTRY_INCOMPLETE",
                "trade_id": trade.trade_id,
                "trade_state": trade.state.value,
                "recovery_required": trade.recovery_required,
            }

        entry_pair = entry_quotes["pair"]
        entry_premium = self._decimal(
            execution["combined_entry_premium"]
        )

        # Fetch fresh quotes after entry; never reuse the entry snapshot
        # as though it were a later market observation.
        fresh_quotes = await self.quote_monitor_fn(
            required_quantity=self.quantity,
            required_snapshots=self.required_snapshots,
            interval_seconds=self.interval_seconds,
        )

        if fresh_quotes.get("status") != "STABLE_PAIR":
            position = {
                "position_status": "OPEN",
                "risk_action": "QUOTE_UNAVAILABLE",
                "reason": "Fresh stable quotes were unavailable",
            }
            self._persist(trade)

            return {
                "status": "CYCLE_COMPLETED",
                "execution_mode": self.EXECUTION_MODE,
                "trade_id": trade.trade_id,
                "trade_state": trade.state.value,
                "entry": execution,
                "position": position,
                "exit_state": None,
                "recovery_required": False,
                "database_snapshot": self.storage.load_trade_snapshot(
                    trade.trade_id
                ),
            }

        fresh_pair = fresh_quotes.get("pair")

        if not self._same_contract_pair(entry_pair, fresh_pair):
            position = {
                "position_status": "OPEN",
                "risk_action": "QUOTE_PAIR_CHANGED",
                "reason": "Fresh quotes do not match the entered contracts",
            }
            self._persist(trade)

            return {
                "status": "CYCLE_COMPLETED",
                "execution_mode": self.EXECUTION_MODE,
                "trade_id": trade.trade_id,
                "trade_state": trade.state.value,
                "entry": execution,
                "position": position,
                "exit_state": None,
                "recovery_required": False,
                "database_snapshot": self.storage.load_trade_snapshot(
                    trade.trade_id
                ),
            }

        try:
            buyback_cost = self._calculate_buyback_cost(
                fresh_pair,
                trade.requested_quantity,
            )
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            position = {
                "position_status": "OPEN",
                "risk_action": "INVALID_FRESH_QUOTE",
                "reason": str(exc),
            }
            self._persist(trade)

            return {
                "status": "CYCLE_COMPLETED",
                "execution_mode": self.EXECUTION_MODE,
                "trade_id": trade.trade_id,
                "trade_state": trade.state.value,
                "entry": execution,
                "position": position,
                "exit_state": None,
                "recovery_required": False,
                "database_snapshot": self.storage.load_trade_snapshot(
                    trade.trade_id
                ),
            }

        position = self.position_monitor_fn(
            entry_premium=entry_premium,
            current_buyback_cost=buyback_cost,
        )

        exit_state = None

        if position["risk_action"] in ("TAKE_PROFIT", "STOP_LOSS"):
            try:
                exit_state = self._simulate_exit(trade, fresh_pair)
            except Exception as exc:
                self._mark_recovery(
                    trade,
                    f"Simulated exit incomplete: {exc}",
                )
                exit_state = "RECOVERY_REQUIRED"

        self._persist(trade)

        result = {
            "status": "CYCLE_COMPLETED",
            "execution_mode": self.EXECUTION_MODE,
            "trade_id": trade.trade_id,
            "trade_state": trade.state.value,
            "entry": execution,
            "position": position,
            "exit_state": exit_state,
            "recovery_required": trade.recovery_required,
            "recovery_reason": trade.recovery_reason,
            "database_snapshot": self.storage.load_trade_snapshot(
                trade.trade_id
            ),
        }

        print("\n========== ENGINE RESULT ==========")
        print("Trade ID:", result["trade_id"])
        print("Trade state:", result["trade_state"])
        print("Risk action:", position["risk_action"])
        print("Exit state:", exit_state)
        print("Recovery required:", trade.recovery_required)
        print("Execution mode:", self.EXECUTION_MODE)
        print("===================================")

        return result

    def inspect_recovery(self, trade_id):
        """
        Inspect persisted state without reconstructing a manager,
        resuming a trade or submitting an exchange order.
        """
        snapshot = self.storage.load_trade_snapshot(trade_id)

        if snapshot is None:
            return {
                "status": "NOT_FOUND",
                "trade_id": str(trade_id),
            }

        trade_data = snapshot["trade"]
        state = trade_data["state"]

        exposed_legs = [
            leg
            for leg in snapshot["legs"]
            if self._decimal(leg["entry_filled_quantity"])
            > self._decimal(leg["exit_filled_quantity"])
        ]

        recovery_required = bool(
            trade_data.get("recovery_required", 0)
        )

        if state in ("CLOSED", "FAILED") and not exposed_legs:
            recovery_status = "NO_OPEN_EXPOSURE_REPORTED"
        else:
            recovery_status = "RECOVERY_REVIEW_REQUIRED"

        return {
            "status": recovery_status,
            "trade_id": str(trade_id),
            "snapshot": snapshot,
            "exposed_legs": [leg["leg"] for leg in exposed_legs],
            "recovery_required": recovery_required,
            "recovery_reason": trade_data.get("recovery_reason"),
            "automatic_resume": False,
            "exchange_reconciliation": False,
        }

    def close(self):
        self.storage.close()


async def main():
    engine = TradingEngine()

    try:
        result = await engine.run_once()
        print("\nFINAL STATUS:", result["status"])
    finally:
        engine.close()


if __name__ == "__main__":
    asyncio.run(main())
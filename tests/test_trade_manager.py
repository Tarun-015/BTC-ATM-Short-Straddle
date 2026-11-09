
from decimal import Decimal

from src.straddle.trade_manager import TradeManager
from src.straddle.trade_state import TradeState, LegState


def make_open_trade():
    trade = TradeManager("TRADE-001")
    trade.start_entry()
    trade.record_entry_fill("CALL", "0.01")
    trade.record_entry_fill("PUT", "0.01")
    return trade


def make_recovery_trade():
    trade = TradeManager("TRADE-001")
    trade.start_entry()
    trade.record_entry_fill("CALL", "0.01")
    trade.update_leg("PUT", LegState.FAILED)
    return trade


# Initial state and entry

def test_initial_trade_state():
    trade = TradeManager("TRADE-001")

    assert trade.state == TradeState.CREATED
    assert trade.legs["CALL"] == LegState.PENDING
    assert trade.legs["PUT"] == LegState.PENDING


def test_start_entry():
    trade = TradeManager("TRADE-001")

    assert trade.start_entry() is True
    assert trade.state == TradeState.ENTRY_PENDING


def test_both_legs_filled_opens_trade():
    trade = make_open_trade()

    assert trade.state == TradeState.OPEN


def test_single_leg_fill_marks_partial():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    trade.record_entry_fill("CALL", "0.01")

    assert trade.state == TradeState.PARTIALLY_FILLED


def test_exit_requested_once():
    trade = make_open_trade()

    assert trade.request_exit() is True
    assert trade.request_exit() is False
    assert trade.state == TradeState.EXIT_PENDING


def test_unknown_leg_rejected():
    trade = TradeManager("TRADE-001")

    assert trade.update_leg("UNKNOWN", LegState.FILLED) is False


def test_invalid_leg_state_rejected():
    trade = TradeManager("TRADE-001")

    assert trade.update_leg("CALL", "FILLED") is False


# Normal exit

def test_both_legs_closed_closes_trade():
    trade = make_open_trade()
    trade.request_exit()

    assert trade.record_exit_fill("CALL", "0.01") is True
    assert trade.record_exit_fill("PUT", "0.01") is True

    assert trade.state == TradeState.CLOSED


def test_trade_not_closed_when_one_leg_remains_open():
    trade = make_open_trade()
    trade.request_exit()

    trade.record_exit_fill("CALL", "0.01")

    assert trade.state == TradeState.EXIT_PENDING
    assert trade.legs["PUT"] == LegState.EXIT_PENDING


def test_duplicate_leg_close_confirmation_rejected():
    trade = make_open_trade()
    trade.request_exit()

    assert trade.record_exit_fill("CALL", "0.01") is True
    assert trade.confirm_leg_closed("CALL") is False


def test_closed_leg_cannot_be_updated_again():
    trade = make_open_trade()
    trade.request_exit()
    trade.record_exit_fill("CALL", "0.01")

    assert trade.update_leg("CALL", LegState.FILLED) is False


# Failed entry and recovery

def test_failed_leg_marks_trade_recovery_required():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    trade.record_entry_fill("CALL", "0.01")
    trade.update_leg("PUT", LegState.FAILED)

    assert trade.state == TradeState.RECOVERY_REQUIRED


def test_failed_trade_cannot_request_normal_exit():
    trade = make_recovery_trade()

    assert trade.request_exit() is False


def test_recovery_exit_moves_exposed_leg_to_exit_pending():
    trade = make_recovery_trade()

    assert trade.request_recovery_exit() is True
    assert trade.legs["CALL"] == LegState.EXIT_PENDING
    assert trade.state == TradeState.RECOVERY_PENDING


def test_recovery_confirmation_removes_open_exposure():
    trade = make_recovery_trade()
    trade.request_recovery_exit()

    assert trade.record_exit_fill("CALL", "0.01") is True

    assert trade.remaining_exposure("CALL") == Decimal("0")
    assert trade.state == TradeState.FAILED


def test_duplicate_recovery_exit_is_rejected():
    trade = make_recovery_trade()

    assert trade.request_recovery_exit() is True
    assert trade.request_recovery_exit() is False


# State transition safety

def test_filled_leg_cannot_return_to_pending():
    trade = make_open_trade()

    assert trade.update_leg("CALL", LegState.PENDING) is False


def test_filled_leg_cannot_return_to_partial():
    trade = make_open_trade()

    assert trade.update_leg(
        "CALL", LegState.PARTIALLY_FILLED
    ) is False


def test_pending_leg_cannot_be_closed_directly():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    assert trade.update_leg("CALL", LegState.CLOSED) is False


def test_duplicate_filled_update_is_accepted():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    assert trade.update_leg("CALL", LegState.FILLED) is True
    assert trade.update_leg("CALL", LegState.FILLED) is True


def test_failed_leg_cannot_be_reopened():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    trade.update_leg("CALL", LegState.FAILED)

    assert trade.update_leg("CALL", LegState.FILLED) is False


# Entry quantity tracking

def test_partial_fill_quantity_tracking():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    assert trade.record_entry_fill("CALL", "0.004") is True

    assert trade.filled_quantities["CALL"] == Decimal("0.004")
    assert trade.remaining_quantity("CALL") == Decimal("0.006")


def test_multiple_fills_complete_leg():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    assert trade.record_entry_fill("CALL", "0.004") is True
    assert trade.record_entry_fill("CALL", "0.006") is True

    assert trade.filled_quantities["CALL"] == Decimal("0.010")
    assert trade.legs["CALL"] == LegState.FILLED


def test_fill_cannot_exceed_requested_quantity():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    assert trade.record_entry_fill("CALL", "0.011") is False
    assert trade.filled_quantities["CALL"] == Decimal("0")


def test_invalid_fill_quantity_rejected():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    assert trade.record_entry_fill("CALL", "-0.01") is False
    assert trade.record_entry_fill("CALL", "invalid") is False
    assert trade.record_entry_fill("CALL", "0") is False


def test_call_and_put_fill_quantities_are_independent():
    trade = TradeManager("TRADE-001")
    trade.start_entry()

    trade.record_entry_fill("CALL", "0.004")
    trade.record_entry_fill("PUT", "0.007")

    assert trade.filled_quantities["CALL"] == Decimal("0.004")
    assert trade.filled_quantities["PUT"] == Decimal("0.007")


# Exit quantity tracking

def test_partial_exit_tracks_remaining_exposure():
    trade = make_open_trade()
    trade.request_exit()

    assert trade.record_exit_fill("CALL", "0.004") is True

    assert trade.exit_filled_quantities["CALL"] == Decimal("0.004")
    assert trade.remaining_exposure("CALL") == Decimal("0.006")
    assert trade.legs["CALL"] == LegState.EXIT_PENDING


def test_complete_exit_closes_leg():
    trade = make_open_trade()
    trade.request_exit()

    trade.record_exit_fill("CALL", "0.010")

    assert trade.legs["CALL"] == LegState.CLOSED
    assert trade.remaining_exposure("CALL") == Decimal("0")


def test_exit_fill_cannot_exceed_entry_fill():
    trade = make_open_trade()
    trade.request_exit()

    assert trade.record_exit_fill("CALL", "0.011") is False
    assert trade.remaining_exposure("CALL") == Decimal("0.010")


def test_exit_confirmation_rejected_for_partial_buyback():
    trade = make_open_trade()
    trade.request_exit()

    trade.record_exit_fill("CALL", "0.004")

    assert trade.confirm_leg_closed("CALL") is False


def test_recovery_exit_supports_partial_buyback():
    trade = make_recovery_trade()
    trade.request_recovery_exit()

    assert trade.record_exit_fill("CALL", "0.002") is True

    assert trade.remaining_exposure("CALL") == Decimal("0.008")
    assert trade.state == TradeState.RECOVERY_PENDING


# Exit failure and retry tracking

def test_exit_failure_preserves_open_exposure():
    trade = make_open_trade()
    trade.request_exit()

    assert trade.record_exit_failure("CALL") is True
    assert trade.remaining_exposure("CALL") == Decimal("0.01")
    assert trade.legs["CALL"] == LegState.EXIT_PENDING


def test_exit_retry_count_increases():
    trade = make_open_trade()
    trade.request_exit()

    trade.record_exit_failure("CALL")

    assert trade.exit_retry_counts["CALL"] == 1


def test_exit_retry_limit_is_enforced():
    trade = make_open_trade()
    trade.request_exit()

    for _ in range(3):
        assert trade.record_exit_failure("CALL") is True

    assert trade.record_exit_failure("CALL") is False
    assert trade.can_retry_exit("CALL") is False


def test_exit_retry_tracking_is_independent_per_leg():
    trade = make_open_trade()
    trade.request_exit()

    trade.record_exit_failure("CALL")

    assert trade.exit_retry_counts["CALL"] == 1
    assert trade.exit_retry_counts["PUT"] == 0
    assert trade.can_retry_exit("PUT") is True


def test_invalid_leg_exit_failure_rejected():
    trade = TradeManager("TRADE-001")

    assert trade.record_exit_failure("UNKNOWN") is False
    assert trade.can_retry_exit("UNKNOWN") is False


# Order tracking

def test_register_entry_order():
    trade = TradeManager("TRADE-001")

    assert trade.register_order("CALL", "ENTRY", "ORDER-001") is True
    assert trade.orders["ORDER-001"]["status"] == "NEW"


def test_register_order_rejects_unknown_leg():
    trade = TradeManager("TRADE-001")

    assert trade.register_order("UNKNOWN", "ENTRY", "ORDER-001") is False


def test_register_order_rejects_duplicate_id():
    trade = TradeManager("TRADE-001")

    assert trade.register_order("CALL", "ENTRY", "ORDER-001") is True
    assert trade.register_order("PUT", "ENTRY", "ORDER-001") is False


def test_order_status_updates():
    trade = TradeManager("TRADE-001")
    trade.register_order("CALL", "ENTRY", "ORDER-001")

    assert trade.update_order_status("ORDER-001", "OPEN") is True
    assert trade.update_order_status(
        "ORDER-001", "PARTIALLY_FILLED"
    ) is True


def test_order_cannot_return_from_filled_to_open():
    trade = TradeManager("TRADE-001")
    trade.register_order("CALL", "ENTRY", "ORDER-001")

    trade.update_order_status("ORDER-001", "FILLED")

    assert trade.update_order_status("ORDER-001", "OPEN") is False


def test_unknown_order_status_update_rejected():
    trade = TradeManager("TRADE-001")

    assert trade.update_order_status("UNKNOWN", "FILLED") is False


# Execution events

def test_entry_execution_event_records_fill():
    trade = TradeManager("TRADE-001")
    trade.start_entry()
    trade.register_order("CALL", "ENTRY", "ENTRY-CALL")

    assert trade.record_execution_event(
        "ENTRY-CALL",
        "EVENT-001",
        "0.004",
        "100",
    ) is True

    assert trade.filled_quantities["CALL"] == Decimal("0.004")
    assert trade.orders["ENTRY-CALL"]["status"] == "PARTIALLY_FILLED"


def test_duplicate_execution_event_rejected():
    trade = TradeManager("TRADE-001")
    trade.start_entry()
    trade.register_order("CALL", "ENTRY", "ENTRY-CALL")

    assert trade.record_execution_event(
        "ENTRY-CALL", "EVENT-001", "0.004"
    ) is True

    assert trade.record_execution_event(
        "ENTRY-CALL", "EVENT-001", "0.004"
    ) is False


def test_execution_event_rejects_unknown_order():
    trade = TradeManager("TRADE-001")

    assert trade.record_execution_event(
        "UNKNOWN", "EVENT-001", "0.004"
    ) is False


def test_execution_event_rejects_invalid_price():
    trade = TradeManager("TRADE-001")
    trade.start_entry()
    trade.register_order("CALL", "ENTRY", "ENTRY-CALL")

    assert trade.record_execution_event(
        "ENTRY-CALL", "EVENT-001", "0.004", "-1"
    ) is False


def test_exit_execution_event_records_buyback():
    trade = make_open_trade()
    trade.request_exit()
    trade.register_order("CALL", "EXIT", "EXIT-CALL")

    assert trade.record_execution_event(
        "EXIT-CALL", "EVENT-EXIT-001", "0.01", "95"
    ) is True

    assert trade.remaining_exposure("CALL") == Decimal("0")
    assert trade.legs["CALL"] == LegState.CLOSED


def test_execution_events_are_recorded():
    trade = TradeManager("TRADE-001")
    trade.start_entry()
    trade.register_order("CALL", "ENTRY", "ENTRY-CALL")

    trade.record_execution_event(
        "ENTRY-CALL", "EVENT-001", "0.004", "100"
    )

    assert len(trade.execution_events) == 1
    assert trade.execution_events[0]["event_id"] == "EVENT-001"
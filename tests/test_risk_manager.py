
import pytest

from src.straddle.risk_manager import (
    calculate_risk_thresholds,
    evaluate_risk,
)


def test_calculate_risk_thresholds():
    result = calculate_risk_thresholds(100)

    assert result["entry_premium"] == 100
    assert result["take_profit_cost"] == 98
    assert result["stop_loss_cost"] == 101


def test_take_profit_triggered():
    result = evaluate_risk(100, 97)

    assert result["action"] == "TAKE_PROFIT"


def test_stop_loss_triggered():
    result = evaluate_risk(100, 102)

    assert result["action"] == "STOP_LOSS"


def test_hold_when_between_thresholds():
    result = evaluate_risk(100, 99)

    assert result["action"] == "HOLD"


def test_take_profit_boundary():
    result = evaluate_risk(100, 98)

    assert result["action"] == "TAKE_PROFIT"


def test_stop_loss_boundary():
    result = evaluate_risk(100, 101)

    assert result["action"] == "STOP_LOSS"


def test_invalid_entry_premium():
    with pytest.raises(ValueError):
        calculate_risk_thresholds(0)


def test_invalid_current_buyback_cost():
    result = evaluate_risk(100, -5)

    assert result["action"] == "INVALID_PRICE"

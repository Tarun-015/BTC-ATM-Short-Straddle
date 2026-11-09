
from src.straddle.position_monitor import monitor_position


def test_position_holds_between_thresholds():
    result = monitor_position(100, 99)

    assert result["position_status"] == "OPEN"
    assert result["risk_action"] == "HOLD"


def test_position_triggers_take_profit():
    result = monitor_position(100, 97)

    assert result["risk_action"] == "TAKE_PROFIT"


def test_position_triggers_stop_loss():
    result = monitor_position(100, 102)

    assert result["risk_action"] == "STOP_LOSS"


def test_position_returns_thresholds():
    result = monitor_position(100, 99)

    assert result["take_profit_cost"] == "98.00"
    assert result["stop_loss_cost"] == "101.00"

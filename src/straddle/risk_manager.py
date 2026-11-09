
from decimal import Decimal, InvalidOperation


STOP_LOSS_PERCENT = Decimal("0.01")
TAKE_PROFIT_PERCENT = Decimal("0.02")


def to_decimal(value):
    """Convert input into a finite positive Decimal."""
    try:
        number = Decimal(str(value))

        if not number.is_finite():
            return None

        return number

    except (InvalidOperation, ValueError, TypeError):
        return None


def calculate_risk_thresholds(entry_premium):
    """Calculate buyback cost thresholds for a short straddle."""

    entry = to_decimal(entry_premium)

    if entry is None or entry <= 0:
        raise ValueError("Entry premium must be a positive finite number")

    take_profit = entry * (Decimal("1") - TAKE_PROFIT_PERCENT)
    stop_loss = entry * (Decimal("1") + STOP_LOSS_PERCENT)

    return {
        "entry_premium": entry,
        "take_profit_cost": take_profit,
        "stop_loss_cost": stop_loss,
    }


def evaluate_risk(entry_premium, current_buyback_cost):
    """Determine whether to hold, take profit, or stop loss."""

    thresholds = calculate_risk_thresholds(entry_premium)
    current_cost = to_decimal(current_buyback_cost)

    if current_cost is None or current_cost < 0:
        return {
            "action": "INVALID_PRICE",
            "reason": "Current buyback cost must be finite and non-negative",
        }

    if current_cost <= thresholds["take_profit_cost"]:
        action = "TAKE_PROFIT"

    elif current_cost >= thresholds["stop_loss_cost"]:
        action = "STOP_LOSS"

    else:
        action = "HOLD"

    return {
        "action": action,
        "entry_premium": str(thresholds["entry_premium"]),
        "current_buyback_cost": str(current_cost),
        "take_profit_cost": str(thresholds["take_profit_cost"]),
        "stop_loss_cost": str(thresholds["stop_loss_cost"]),
    }

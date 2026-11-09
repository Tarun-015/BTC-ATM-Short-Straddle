
from src.straddle.risk_manager import evaluate_risk


def monitor_position(entry_premium, current_buyback_cost):
    """Monitor an open simulated short-straddle position."""

    result = evaluate_risk(
        entry_premium=entry_premium,
        current_buyback_cost=current_buyback_cost,
    )

    return {
        "position_status": "OPEN",
        "risk_action": result["action"],
        "entry_premium": str(entry_premium),
        "current_buyback_cost": result["current_buyback_cost"]
        if "current_buyback_cost" in result
        else str(current_buyback_cost),
        "take_profit_cost": result.get("take_profit_cost"),
        "stop_loss_cost": result.get("stop_loss_cost"),
    }

from datetime import datetime, timezone
from decimal import Decimal
import math

from src.straddle.risk_manager import calculate_risk_thresholds


MAX_MARKET_AGE_SECONDS = 15


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _age_seconds(timestamp, now):
    try:
        captured = datetime.fromisoformat(timestamp)
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        return max(0.0, (now - captured.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def build_market_view(snapshot, pair, now=None):
    now = now or datetime.now(timezone.utc)
    if snapshot is None:
        return {
            "status": "NO_DATA",
            "freshness": "NO_DATA",
            "age_seconds": None,
            "index_price": None,
            "pair_available": False,
            "quote_valid": False,
            "risk_preview": None,
        }

    age = _age_seconds(snapshot.get("captured_at"), now)
    freshness = (
        "UNKNOWN" if age is None
        else "FRESH" if age <= MAX_MARKET_AGE_SECONDS
        else "STALE"
    )
    index_price = _number(snapshot.get("index_price"))
    pair_available = snapshot.get("status") == "PAIR_FOUND" and pair is not None
    quote_valid = False
    call_spread = None
    put_spread = None
    risk_preview = None

    if pair_available:
        call_bid = _number(pair.get("call_bid"))
        call_ask = _number(pair.get("call_ask"))
        put_bid = _number(pair.get("put_bid"))
        put_ask = _number(pair.get("put_ask"))
        quote_valid = all(
            value is not None and value > 0
            for value in (call_bid, call_ask, put_bid, put_ask)
        ) and call_ask >= call_bid and put_ask >= put_bid

        if quote_valid:
            call_spread = call_ask - call_bid
            put_spread = put_ask - put_bid
            entry_premium = _number(pair.get("combined_entry_bid"))
            if entry_premium is not None and entry_premium > 0:
                thresholds = calculate_risk_thresholds(Decimal(str(entry_premium)))
                risk_preview = {
                    "entry_premium": float(thresholds["entry_premium"]),
                    "take_profit_cost": float(thresholds["take_profit_cost"]),
                    "stop_loss_cost": float(thresholds["stop_loss_cost"]),
                }

    return {
        "status": snapshot.get("status", "UNKNOWN"),
        "reason": snapshot.get("reason"),
        "freshness": freshness,
        "age_seconds": age,
        "index_price": index_price,
        "pair_available": pair_available,
        "quote_valid": quote_valid,
        "call_spread": call_spread,
        "put_spread": put_spread,
        "risk_preview": risk_preview,
    }

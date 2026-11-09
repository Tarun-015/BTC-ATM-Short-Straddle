
from decimal import Decimal


def to_decimal(value):
    """Safely convert a value to Decimal."""
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return Decimal("0")


def simulate_short_straddle_entry(
    stable_result,
    quantity=0.01,
):
    """
    Simulate selling one Call and one Put.

    This function never submits exchange orders.
    """

    if stable_result.get("status") != "STABLE_PAIR":
        return {
            "status": "REJECTED",
            "reason": "A stable Call-Put pair is required",
        }

    pair = stable_result.get("pair")

    if not pair:
        return {
            "status": "REJECTED",
            "reason": "Pair information is missing",
        }

    qty = to_decimal(quantity)

    if qty <= 0:
        return {
            "status": "REJECTED",
            "reason": "Invalid order quantity",
        }

    call = pair["call"]
    put = pair["put"]

    call_bid = to_decimal(call.bid1_price)
    put_bid = to_decimal(put.bid1_price)

    call_size = to_decimal(call.bid1_size)
    put_size = to_decimal(put.bid1_size)

    if call_bid <= 0 or put_bid <= 0:
        return {
            "status": "REJECTED",
            "reason": "Invalid bid price",
        }

    if call_size < qty or put_size < qty:
        return {
            "status": "REJECTED",
            "reason": "Insufficient displayed bid quantity",
        }

    call_multiplier = to_decimal(
        pair["call_instrument"].multiplier
    )
    put_multiplier = to_decimal(
        pair["put_instrument"].multiplier
    )

    if call_multiplier <= 0 or put_multiplier <= 0:
        return {
            "status": "REJECTED",
            "reason": "Invalid contract multiplier",
        }

    if call_multiplier != put_multiplier:
        return {
            "status": "REJECTED",
            "reason": "Call and Put multipliers differ",
        }

    call_premium = call_bid * qty * call_multiplier
    put_premium = put_bid * qty * put_multiplier

    total_premium = call_premium + put_premium

    return {
        "status": "SIMULATED_FILLED",
        "execution_mode": "SIMULATION_ONLY",
        "call": {
            "symbol": call.symbol,
            "side": "SELL",
            "quantity": str(qty),
            "simulated_fill_price": str(call_bid),
            "simulated_premium": str(call_premium),
        },
        "put": {
            "symbol": put.symbol,
            "side": "SELL",
            "quantity": str(qty),
            "simulated_fill_price": str(put_bid),
            "simulated_premium": str(put_premium),
        },
        "combined_entry_premium": str(total_premium),
        "fees_included": False,
    }

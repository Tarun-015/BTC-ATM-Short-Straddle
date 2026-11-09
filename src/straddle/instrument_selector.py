
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation


def get_number(value):
    """Safely convert exchange values into float."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def quantity_is_valid(instrument, quantity):
    """Validate minimum quantity and exact quantity increment."""
    try:
        qty = Decimal(str(quantity))
        minimum = Decimal(str(instrument.min_quantity))
        increment = Decimal(str(instrument.size_increment))
    except (TypeError, ValueError, InvalidOperation):
        return False

    if increment <= 0 or qty < minimum:
        return False

    return qty % increment == 0


def parse_symbol(symbol):
    """
    Parse Bybit option symbol.

    Example:
    BTC-29JAN27-75000-C-USDT
    """
    parts = symbol.split("-")

    if len(parts) != 5:
        return None

    if parts[0] != "BTC":
        return None

    try:
        expiry = datetime.strptime(parts[1], "%d%b%y").date()
        strike = float(parts[2])
    except (ValueError, TypeError):
        return None

    option_type = parts[3]
    settlement = parts[4]

    if option_type not in ("C", "P"):
        return None

    return {
        "underlying": parts[0],
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "settlement": settlement,
    }


def is_usable_quote(ticker, required_quantity):
    """Require valid two-sided quotes and sufficient displayed size."""
    bid = get_number(ticker.bid1_price)
    ask = get_number(ticker.ask1_price)
    bid_size = get_number(ticker.bid1_size)
    ask_size = get_number(ticker.ask1_size)

    return (
        bid > 0
        and ask > 0
        and bid <= ask
        and bid_size >= required_quantity
        and ask_size >= required_quantity
    )


def select_best_pair(
    instruments,
    tickers,
    index_price,
    required_quantity=0.01,
):
    """
    Select the nearest liquid BTC USDT Call-Put pair.

    Selection rules:
    1. BTC underlying only.
    2. USDT settlement only.
    3. Same expiry and strike for both legs.
    4. Compatible contract specifications.
    5. Valid quantity increments.
    6. Both legs must have usable two-sided quotes.
    7. Earliest expiry, then nearest strike to index price.
    """

    index_price = get_number(index_price)

    if index_price <= 0 or required_quantity <= 0:
        return {
            "status": "NO_TRADE",
            "reason": "Invalid index price or order quantity",
        }

    # Build instrument lookup using exchange instrument IDs.
    instrument_map = {}

    for instrument in instruments:
        instrument_id = str(instrument.id)

        for ticker in tickers:
            if instrument_id.startswith(ticker.symbol + "-OPTION."):
                instrument_map[ticker.symbol] = instrument

    # Group tickers by expiry, strike and settlement.
    pairs = defaultdict(dict)

    for ticker in tickers:
        parsed = parse_symbol(ticker.symbol)

        if parsed is None:
            continue

        if parsed["settlement"] != "USDT":
            continue

        if parsed["expiry"] <= datetime.now().date():
            continue

        key = (
            parsed["expiry"],
            parsed["strike"],
            parsed["settlement"],
        )

        pairs[key][parsed["option_type"]] = ticker

    candidates = []

    for (expiry, strike, settlement), legs in pairs.items():

        if "C" not in legs or "P" not in legs:
            continue

        call = legs["C"]
        put = legs["P"]

        call_instrument = instrument_map.get(call.symbol)
        put_instrument = instrument_map.get(put.symbol)

        if call_instrument is None or put_instrument is None:
            continue

        # Verify contract compatibility.
        if (
            call_instrument.multiplier
            != put_instrument.multiplier
        ):
            continue

        if (
            call_instrument.settlement_currency
            != put_instrument.settlement_currency
        ):
            continue

        if (
            str(call_instrument.settlement_currency) != "USDT"
        ):
            continue

        # Validate order quantity independently for both contracts.
        if not quantity_is_valid(call_instrument, required_quantity):
            continue

        if not quantity_is_valid(put_instrument, required_quantity):
            continue

        # Both legs must have valid quotes and sufficient size.
        if not is_usable_quote(call, required_quantity):
            continue

        if not is_usable_quote(put, required_quantity):
            continue

        candidates.append({
            "expiry": expiry,
            "strike": strike,
            "settlement": settlement,
            "distance_from_atm": abs(strike - index_price),
            "call": call,
            "put": put,
            "call_instrument": call_instrument,
            "put_instrument": put_instrument,
            "combined_entry_bid": (
                get_number(call.bid1_price)
                + get_number(put.bid1_price)
            ),
            "combined_buyback_ask": (
                get_number(call.ask1_price)
                + get_number(put.ask1_price)
            ),
        })

    if not candidates:
        return {
            "status": "NO_TRADE",
            "reason": "No matching pair has sufficient two-sided liquidity",
        }

    # Prefer nearest eligible expiry, then nearest ATM strike.
    candidates.sort(
        key=lambda item: (
            item["expiry"],
            item["distance_from_atm"],
        )
    )

    result = candidates[0]
    result["status"] = "PAIR_FOUND"

    return result

import asyncio
from collections import defaultdict
from datetime import datetime

from nautilus_trader.adapters.bybit import (
    BybitHttpClient,
    BybitProductType,
    BybitTickersParams,
)

from src.straddle.instrument_selector import (
    get_number,
    parse_symbol,
    is_usable_quote,
    quantity_is_valid,
    select_best_pair,
)


def print_quoted_contracts(tickers, quantity):
    """Display contracts that individually have usable quotes."""

    print("\n========== INDIVIDUAL QUOTED CONTRACTS ==========")

    count = 0

    for ticker in tickers:
        if not is_usable_quote(ticker, quantity):
            continue

        parsed = parse_symbol(ticker.symbol)

        if not parsed or parsed["settlement"] != "USDT":
            continue

        print(
            f"{ticker.symbol} | "
            f"Bid: {ticker.bid1_price} | "
            f"Ask: {ticker.ask1_price} | "
            f"Bid Size: {ticker.bid1_size} | "
            f"Ask Size: {ticker.ask1_size}"
        )

        count += 1

    print("Total individually quoted contracts:", count)
    print("=================================================")


def diagnose_market(instruments, tickers, index_price, quantity):
    """Report why BTC option pairs are rejected."""

    instrument_map = {}

    for instrument in instruments:
        instrument_id = str(instrument.id)

        for ticker in tickers:
            if instrument_id.startswith(ticker.symbol + "-OPTION."):
                instrument_map[ticker.symbol] = instrument

    pairs = defaultdict(dict)

    for ticker in tickers:
        parsed = parse_symbol(ticker.symbol)

        if not parsed or parsed["settlement"] != "USDT":
            continue

        if parsed["expiry"] <= datetime.now().date():
            continue

        key = (
            parsed["expiry"],
            parsed["strike"],
            parsed["settlement"],
        )

        pairs[key][parsed["option_type"]] = ticker

    complete = 0
    missing_instrument = 0
    incompatible = 0
    invalid_quantity = 0
    call_quoted = 0
    put_quoted = 0
    both_quoted = 0

    for key, legs in pairs.items():

        if "C" not in legs or "P" not in legs:
            continue

        complete += 1

        call = legs["C"]
        put = legs["P"]

        ci = instrument_map.get(call.symbol)
        pi = instrument_map.get(put.symbol)

        if ci is None or pi is None:
            missing_instrument += 1
            continue

        if (
            ci.multiplier != pi.multiplier
            or ci.settlement_currency != pi.settlement_currency
            or str(ci.settlement_currency) != "USDT"
        ):
            incompatible += 1
            continue

        if (
            not quantity_is_valid(ci, quantity)
            or not quantity_is_valid(pi, quantity)
        ):
            invalid_quantity += 1
            continue

        call_ok = is_usable_quote(call, quantity)
        put_ok = is_usable_quote(put, quantity)

        if call_ok:
            call_quoted += 1

        if put_ok:
            put_quoted += 1

        if call_ok and put_ok:
            both_quoted += 1

    print("\n========== MARKET DIAGNOSTICS ==========")
    print("Complete Call-Put pairs:", complete)
    print("Missing instrument metadata:", missing_instrument)
    print("Incompatible contracts:", incompatible)
    print("Invalid order quantity:", invalid_quantity)
    print("Pairs with usable Call quotes:", call_quoted)
    print("Pairs with usable Put quotes:", put_quoted)
    print("Pairs with both usable quotes:", both_quoted)
    print("BTC index price:", f"{index_price:,.2f}")
    print("Required quantity:", quantity)
    print("========================================")


async def scan_market(required_quantity=0.01):

    client = BybitHttpClient(testnet=True)

    print("\nConnecting to Bybit Testnet public API...")

    instruments = await client.request_instruments(
        BybitProductType.OPTION,
        base_coin="BTC",
    )

    print("BTC instruments received:", len(instruments))

    params = BybitTickersParams(
        category=BybitProductType.OPTION,
        base_coin="BTC",
    )

    tickers = await client.request_tickers(params)

    print("BTC tickers received:", len(tickers))

    if not instruments or not tickers:
        return {
            "status": "NO_TRADE",
            "reason": "Instrument or ticker data unavailable",
        }

    index_prices = [
        get_number(ticker.index_price)
        for ticker in tickers
        if get_number(ticker.index_price) > 0
    ]

    if not index_prices:
        return {
            "status": "NO_TRADE",
            "reason": "BTC index price unavailable",
        }

    index_price = index_prices[0]

    print(f"BTC index price: {index_price:,.2f}")

    result = select_best_pair(
        instruments=instruments,
        tickers=tickers,
        index_price=index_price,
        required_quantity=required_quantity,
    )

    if result["status"] == "NO_TRADE":
        diagnose_market(
            instruments,
            tickers,
            index_price,
            required_quantity,
        )
        print_quoted_contracts(tickers, required_quantity)

    return result


if __name__ == "__main__":

    result = asyncio.run(scan_market())

    print("\n========== MARKET SCAN RESULT ==========")
    print("STATUS:", result["status"])

    if result["status"] == "PAIR_FOUND":
        print("EXPIRY:", result["expiry"])
        print("STRIKE:", result["strike"])
        print("CALL:", result["call"].symbol)
        print("PUT:", result["put"].symbol)
        print("DISTANCE FROM ATM:", result["distance_from_atm"])
        print("COMBINED ENTRY BID:", result["combined_entry_bid"])
        print("COMBINED BUYBACK ASK:", result["combined_buyback_ask"])
    else:
        print("REASON:", result["reason"])

    print("========================================")

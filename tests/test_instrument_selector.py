from types import SimpleNamespace
from datetime import date

from src.straddle.instrument_selector import select_best_pair


def make_instrument(symbol, multiplier=1, min_qty=0.01, increment=0.01):
    return SimpleNamespace(
        id=f"{symbol}-OPTION.BYBIT",
        multiplier=multiplier,
        settlement_currency="USDT",
        min_quantity=min_qty,
        size_increment=increment,
    )


def make_ticker(symbol, bid=100, ask=110, bid_size=1, ask_size=1):
    return SimpleNamespace(
        symbol=symbol,
        bid1_price=bid,
        ask1_price=ask,
        bid1_size=bid_size,
        ask1_size=ask_size,
    )


def make_pair(strike=75000, expiry="29JAN27"):
    call_symbol = f"BTC-{expiry}-{strike}-C-USDT"
    put_symbol = f"BTC-{expiry}-{strike}-P-USDT"

    instruments = [
        make_instrument(call_symbol),
        make_instrument(put_symbol),
    ]

    tickers = [
        make_ticker(call_symbol),
        make_ticker(put_symbol),
    ]

    return instruments, tickers


def test_valid_pair_is_selected():
    instruments, tickers = make_pair()

    result = select_best_pair(
        instruments, tickers, index_price=75000
    )

    assert result["status"] == "PAIR_FOUND"
    assert result["strike"] == 75000


def test_zero_quote_is_rejected():
    instruments, tickers = make_pair()
    tickers[1].bid1_price = 0

    result = select_best_pair(
        instruments, tickers, index_price=75000
    )

    assert result["status"] == "NO_TRADE"


def test_missing_put_is_rejected():
    instruments, tickers = make_pair()
    tickers.pop()

    result = select_best_pair(
        instruments, tickers, index_price=75000
    )

    assert result["status"] == "NO_TRADE"


def test_insufficient_quote_size_is_rejected():
    instruments, tickers = make_pair()
    tickers[1].ask1_size = 0

    result = select_best_pair(
        instruments, tickers, index_price=75000
    )

    assert result["status"] == "NO_TRADE"


def test_incompatible_multiplier_is_rejected():
    instruments, tickers = make_pair()
    instruments[1].multiplier = 2

    result = select_best_pair(
        instruments, tickers, index_price=75000
    )

    assert result["status"] == "NO_TRADE"
    
def test_different_strikes_are_not_paired():
    instruments, tickers = make_pair()

    extra_put = make_ticker("BTC-29JAN27-76000-P-USDT")
    extra_instrument = make_instrument("BTC-29JAN27-76000-P-USDT")

    instruments.append(extra_instrument)
    tickers.append(extra_put)

    result = select_best_pair(
        instruments, tickers, index_price=75000
    )

    # The original 75000 Call-Put pair remains valid.
    assert result["status"] == "PAIR_FOUND"
    assert result["strike"] == 75000


def test_different_expiries_are_not_paired():
    call_symbol = "BTC-29JAN27-75000-C-USDT"
    put_symbol = "BTC-25DEC26-75000-P-USDT"

    instruments = [
        make_instrument(call_symbol),
        make_instrument(put_symbol),
    ]

    tickers = [
        make_ticker(call_symbol),
        make_ticker(put_symbol),
    ]

    result = select_best_pair(
        instruments, tickers, index_price=75000
    )

    assert result["status"] == "NO_TRADE"


def test_invalid_quantity_increment_is_rejected():
    instruments, tickers = make_pair()

    result = select_best_pair(
        instruments,
        tickers,
        index_price=75000,
        required_quantity=0.015,
    )

    assert result["status"] == "NO_TRADE"


def test_invalid_index_price_is_rejected():
    instruments, tickers = make_pair()

    result = select_best_pair(
        instruments, tickers, index_price=0
    )

    assert result["status"] == "NO_TRADE"
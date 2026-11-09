
from types import SimpleNamespace

from src.straddle.simulated_executor import (
    simulate_short_straddle_entry,
)


def make_stable_result():
    call = SimpleNamespace(
        symbol="BTC-29JAN27-75000-C-USDT",
        bid1_price=100,
        bid1_size=1,
    )

    put = SimpleNamespace(
        symbol="BTC-29JAN27-75000-P-USDT",
        bid1_price=50,
        bid1_size=1,
    )

    call_instrument = SimpleNamespace(multiplier=1)
    put_instrument = SimpleNamespace(multiplier=1)

    pair = {
        "call": call,
        "put": put,
        "call_instrument": call_instrument,
        "put_instrument": put_instrument,
    }

    return {
        "status": "STABLE_PAIR",
        "pair": pair,
    }


def test_valid_short_straddle_entry():
    result = simulate_short_straddle_entry(
        make_stable_result(),
        quantity=0.01,
    )

    assert result["status"] == "SIMULATED_FILLED"
    assert result["call"]["side"] == "SELL"
    assert result["put"]["side"] == "SELL"
    assert float(result["combined_entry_premium"]) == 1.50


def test_unstable_pair_is_rejected():
    result = simulate_short_straddle_entry(
        {"status": "NO_STABLE_PAIR"},
        quantity=0.01,
    )

    assert result["status"] == "REJECTED"


def test_insufficient_bid_size_is_rejected():
    stable = make_stable_result()
    stable["pair"]["put"].bid1_size = 0.001

    result = simulate_short_straddle_entry(
        stable,
        quantity=0.01,
    )

    assert result["status"] == "REJECTED"


def test_zero_bid_price_is_rejected():
    stable = make_stable_result()
    stable["pair"]["call"].bid1_price = 0

    result = simulate_short_straddle_entry(
        stable,
        quantity=0.01,
    )

    assert result["status"] == "REJECTED"

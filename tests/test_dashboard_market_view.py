from datetime import datetime, timedelta, timezone

from dashboard.market_view import build_market_view


def make_snapshot(age_seconds=2, status="PAIR_FOUND"):
    captured = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {
        "captured_at": captured.isoformat(),
        "index_price": 75000,
        "status": status,
        "reason": None,
    }


def make_pair():
    return {
        "strike": 75000,
        "call_bid": 60,
        "call_ask": 62,
        "put_bid": 40,
        "put_ask": 42,
        "combined_entry_bid": 100,
        "combined_buyback_ask": 104,
    }


def test_market_view_builds_risk_preview_from_valid_pair():
    result = build_market_view(make_snapshot(), make_pair())
    assert result["freshness"] == "FRESH"
    assert result["pair_available"] is True
    assert result["quote_valid"] is True
    assert result["call_spread"] == 2
    assert result["put_spread"] == 2
    assert result["risk_preview"] == {
        "entry_premium": 100.0,
        "take_profit_cost": 98.0,
        "stop_loss_cost": 101.0,
    }


def test_market_view_marks_old_snapshot_stale():
    result = build_market_view(make_snapshot(age_seconds=30), make_pair())
    assert result["freshness"] == "STALE"
    assert result["quote_valid"] is True


def test_market_view_rejects_crossed_or_invalid_quotes():
    pair = make_pair()
    pair["call_ask"] = 59
    result = build_market_view(make_snapshot(), pair)
    assert result["quote_valid"] is False
    assert result["risk_preview"] is None


def test_market_view_without_pair_has_no_risk_preview():
    result = build_market_view(make_snapshot(status="NO_TRADE"), None)
    assert result["pair_available"] is False
    assert result["risk_preview"] is None


def test_market_view_without_snapshot_is_empty():
    result = build_market_view(None, None)
    assert result["status"] == "NO_DATA"
    assert result["freshness"] == "NO_DATA"
    assert result["index_price"] is None


def test_market_view_rejects_non_finite_values():
    pair = make_pair()
    pair["put_bid"] = float("nan")
    result = build_market_view(make_snapshot(), pair)
    assert result["quote_valid"] is False
    assert result["risk_preview"] is None

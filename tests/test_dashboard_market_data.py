from src.straddle.market_data_storage import MarketDataStorage
from dashboard.data_access import load_dashboard_data


def test_dashboard_reads_latest_market_snapshot_and_pair(tmp_path):
    path = tmp_path / "dashboard.db"
    storage = MarketDataStorage(path)
    storage.save_snapshot(75000, "NO_TRADE", "No liquid pair")
    storage.close()

    data = load_dashboard_data(path)

    assert data["market_snapshot"]["index_price"] == 75000
    assert data["market_snapshot"]["status"] == "NO_TRADE"
    assert data["market_snapshot"]["reason"] == "No liquid pair"
    assert data["selected_pair"] is None


def test_dashboard_reads_worker_heartbeat(tmp_path):
    path = tmp_path / "dashboard.db"
    storage = MarketDataStorage(path)
    storage.update_heartbeat("market-data-worker", "RUNNING", "scan complete")
    storage.close()

    data = load_dashboard_data(path)

    assert data["heartbeat"]["worker_id"] == "market-data-worker"
    assert data["heartbeat"]["status"] == "RUNNING"
    assert data["heartbeat"]["effective_status"] in {"RUNNING", "STALE"}


def test_dashboard_supports_legacy_database_without_market_tables(tmp_path):
    from src.straddle.storage import SQLiteStorage

    path = tmp_path / "legacy.db"
    storage = SQLiteStorage(path)
    storage.close()

    data = load_dashboard_data(path)

    assert data["available"] is True
    assert data["market_snapshot"] is None
    assert data["selected_pair"] is None
    assert data["heartbeat"] is None

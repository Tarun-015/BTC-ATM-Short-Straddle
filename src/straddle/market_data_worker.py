import argparse
import asyncio
import os
from pathlib import Path

from src.straddle.instrument_selector import get_number, select_best_pair
from src.straddle.market_data_storage import MarketDataStorage


async def fetch_market_data():
    from nautilus_trader.adapters.bybit import (
        BybitHttpClient,
        BybitProductType,
        BybitTickersParams,
    )

    client = BybitHttpClient(testnet=True)
    instruments = await client.request_instruments(
        BybitProductType.OPTION,
        base_coin="BTC",
    )
    params = BybitTickersParams(
        category=BybitProductType.OPTION,
        base_coin="BTC",
    )
    tickers = await client.request_tickers(params)
    return instruments, tickers


async def collect_once(storage, required_quantity=0.01, fetcher=None):
    fetcher = fetcher or fetch_market_data
    try:
        instruments, tickers = await fetcher()
        index_prices = [
            get_number(ticker.index_price)
            for ticker in tickers
            if get_number(ticker.index_price) > 0
        ]
        index_price = index_prices[0] if index_prices else None
        if index_price is None:
            storage.save_snapshot(
                None,
                "NO_TRADE",
                "BTC index price unavailable",
            )
            storage.update_heartbeat(
                "market-data-worker",
                "RUNNING",
                "BTC index price unavailable",
            )
            return {"status": "NO_TRADE", "index_price": None}

        result = select_best_pair(
            instruments=instruments,
            tickers=tickers,
            index_price=index_price,
            required_quantity=required_quantity,
        )
        if result.get("status") != "PAIR_FOUND":
            storage.save_snapshot(
                index_price,
                "NO_TRADE",
                result.get("reason", "No eligible option pair"),
            )
            storage.update_heartbeat(
                "market-data-worker",
                "RUNNING",
                "Latest scan: NO_TRADE",
            )
            return {
                "status": "NO_TRADE",
                "index_price": index_price,
                "reason": result.get("reason"),
            }

        storage.save_snapshot(
            index_price,
            "PAIR_FOUND",
            pair=result,
        )
        storage.update_heartbeat(
            "market-data-worker",
            "RUNNING",
            "Latest scan: PAIR_FOUND",
        )
        return {
            "status": "PAIR_FOUND",
            "index_price": index_price,
            "call_symbol": result["call"].symbol,
            "put_symbol": result["put"].symbol,
        }
    except Exception as exc:
        storage.update_heartbeat(
            "market-data-worker",
            "ERROR",
            f"{type(exc).__name__}: {exc}",
        )
        raise


async def run_worker(db_path, interval_seconds=5, required_quantity=0.01):
    storage = MarketDataStorage(db_path)
    storage.update_heartbeat(
        "market-data-worker",
        "STARTING",
        "Worker initializing",
    )
    try:
        while True:
            try:
                result = await collect_once(
                    storage,
                    required_quantity=required_quantity,
                )
                print(result)
            except Exception as exc:
                print(f"Market data collection failed: {exc}")
            await asyncio.sleep(interval_seconds)
    finally:
        storage.update_heartbeat(
            "market-data-worker",
            "STOPPED",
            "Worker shutdown",
        )
        storage.close()


def main():
    parser = argparse.ArgumentParser(
        description="Persist Bybit Testnet BTC option market snapshots"
    )
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parents[2] / "data" / "straddle.db"),
    )
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--quantity", type=float, default=0.01)
    args = parser.parse_args()

    if args.interval < 1:
        parser.error("--interval must be at least 1 second")
    if args.quantity <= 0:
        parser.error("--quantity must be greater than zero")

    print("BTC options market-data worker")
    print("Environment: BYBIT TESTNET")
    print("Execution: DISABLED")
    print("Database:", args.db)
    asyncio.run(
        run_worker(
            args.db,
            interval_seconds=args.interval,
            required_quantity=args.quantity,
        )
    )


if __name__ == "__main__":
    main()

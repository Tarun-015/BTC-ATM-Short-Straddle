
import asyncio

from nautilus_trader.adapters.bybit import (
    BybitHttpClient,
    BybitProductType,
    BybitTickersParams,
)

from src.straddle.instrument_selector import (
    get_number,
    select_best_pair,
)


async def monitor_quotes(
    required_quantity=0.01,
    required_snapshots=3,
    interval_seconds=2,
):
    """Require the same liquid Call-Put pair across consecutive snapshots."""

    client = BybitHttpClient(testnet=True)

    print("Connecting to Bybit Testnet...")
    
    instruments = await client.request_instruments(
        BybitProductType.OPTION,
        base_coin="BTC",
    )

    print("BTC instruments:", len(instruments))

    params = BybitTickersParams(
        category=BybitProductType.OPTION,
        base_coin="BTC",
    )

    stable_count = 0
    previous_pair = None

    for snapshot_number in range(1, required_snapshots + 1):

        print(f"\n========== SNAPSHOT {snapshot_number} ==========")

        tickers = await client.request_tickers(params)

        index_prices = [
            get_number(ticker.index_price)
            for ticker in tickers
            if get_number(ticker.index_price) > 0
        ]

        if not index_prices:
            print("BTC index price unavailable.")
            stable_count = 0
            previous_pair = None
            continue

        index_price = index_prices[0]

        result = select_best_pair(
            instruments=instruments,
            tickers=tickers,
            index_price=index_price,
            required_quantity=required_quantity,
        )

        print(f"BTC index price: {index_price:,.2f}")

        if result["status"] != "PAIR_FOUND":
            print("STATUS: NO_TRADE")
            print("REASON:", result["reason"])

            stable_count = 0
            previous_pair = None

        else:
            current_pair = (
                result["call"].symbol,
                result["put"].symbol,
            )

            print("CALL:", current_pair[0])
            print("PUT:", current_pair[1])
            print("CALL BID:", result["call"].bid1_price)
            print("CALL ASK:", result["call"].ask1_price)
            print("PUT BID:", result["put"].bid1_price)
            print("PUT ASK:", result["put"].ask1_price)

            if current_pair == previous_pair:
                stable_count += 1
            else:
                previous_pair = current_pair
                stable_count = 1

            print("STABLE SNAPSHOTS:", stable_count)

            if stable_count >= required_snapshots:
                print("\nSTABILITY CHECK: PASSED")

                return {
                    "status": "STABLE_PAIR",
                    "pair": result,
                    "stable_snapshots": stable_count,
                    "index_price": index_price,
                }

        if snapshot_number < required_snapshots:
            await asyncio.sleep(interval_seconds)

    print("\nSTABILITY CHECK: FAILED")
    print("No matching pair remained valid across all required snapshots.")

    return {
        "status": "NO_STABLE_PAIR",
        "stable_snapshots": stable_count,
    }


if __name__ == "__main__":

    result = asyncio.run(
        monitor_quotes(
            required_quantity=0.01,
            required_snapshots=3,
            interval_seconds=2,
        )
    )

    print("\n========== QUOTE MONITOR RESULT ==========")
    print("STATUS:", result["status"])

    if result["status"] == "STABLE_PAIR":
        print("Stable snapshots:", result["stable_snapshots"])
        print("Call:", result["pair"]["call"].symbol)
        print("Put:", result["pair"]["put"].symbol)

    print("==========================================")

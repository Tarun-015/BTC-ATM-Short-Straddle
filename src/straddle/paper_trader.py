
import asyncio

from src.straddle.quote_monitor import monitor_quotes
from src.straddle.simulated_executor import (
    simulate_short_straddle_entry,
)


async def run_paper_trading():
    quantity = 0.01

    print("\n========== BTC PAPER TRADING ==========")
    print("Execution mode: SIMULATION ONLY")
    print("Order quantity:", quantity)

    # Step 1: Check quote stability.
    stable_result = await monitor_quotes(
        required_quantity=quantity,
        required_snapshots=3,
        interval_seconds=2,
    )

    # Step 2: Stop if no stable pair exists.
    if stable_result["status"] != "STABLE_PAIR":
        print("\nPAPER TRADE: NOT EXECUTED")
        print("Reason: No stable Call-Put pair available.")
        return

    # Step 3: Simulate selling both option legs.
    execution_result = simulate_short_straddle_entry(
        stable_result=stable_result,
        quantity=quantity,
    )

    print("\n========== EXECUTION RESULT ==========")
    print("STATUS:", execution_result["status"])

    if execution_result["status"] == "SIMULATED_FILLED":
        print("CALL:", execution_result["call"])
        print("PUT:", execution_result["put"])
        print(
            "COMBINED ENTRY PREMIUM:",
            execution_result["combined_entry_premium"],
        )
        print("FEES INCLUDED:", execution_result["fees_included"])

    else:
        print("REASON:", execution_result["reason"])

    print("======================================")


if __name__ == "__main__":
    asyncio.run(run_paper_trading())

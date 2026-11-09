
import argparse

from src.straddle.bybit_connection import build_bybit_data_node


def main():
    parser = argparse.ArgumentParser(
        description="BTC ATM Short Straddle - Public Market Data"
    )

    parser.add_argument(
        "--connect",
        action="store_true",
        help="Connect to Bybit Testnet public options data",
    )

    args = parser.parse_args()

    print("=" * 55)
    print("       BTC ATM SHORT STRADDLE SYSTEM")
    print("=" * 55)
    print("Environment: BYBIT TESTNET")
    print("Product: OPTIONS")
    print("Connection: PUBLIC MARKET DATA")
    print("API credentials: NOT REQUIRED")
    print("Order submission: DISABLED")

    if not args.connect:
        print("\nRun with --connect to start the data node.")
        return

    node = None

    try:
        print("\nBuilding Bybit data node...")
        node = build_bybit_data_node()

        print("Node built successfully.")
        print("\nStarting public market-data connection...")

        node.run()

    except KeyboardInterrupt:
        print("\nShutdown requested by user.")

    finally:
        if node is not None:
            node.dispose()
            print("Node disposed.")


if __name__ == "__main__":
    main()
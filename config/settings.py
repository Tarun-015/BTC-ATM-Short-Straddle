import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_secret: str

    environment: str
    execution_mode: str

    settlement_currency: str
    expiry_policy: str
    order_quantity: str


def load_settings() -> Settings:
    environment = os.getenv("TRADING_ENV", "TESTNET")
    execution_mode = os.getenv("EXECUTION_MODE", "DRY_RUN")

    if environment != "TESTNET":
        raise ValueError(
            "Only Bybit TESTNET is permitted in this project."
        )

    if execution_mode not in {"DRY_RUN", "TESTNET"}:
        raise ValueError("Invalid execution mode.")

    if execution_mode == "TESTNET":
        if not os.getenv("BYBIT_TESTNET_API_KEY"):
            raise ValueError("Missing Testnet API key.")

        if not os.getenv("BYBIT_TESTNET_API_SECRET"):
            raise ValueError("Missing Testnet API secret.")

    return Settings(
        api_key=os.getenv("BYBIT_TESTNET_API_KEY", ""),
        api_secret=os.getenv("BYBIT_TESTNET_API_SECRET", ""),
        environment=environment,
        execution_mode=execution_mode,
        settlement_currency=os.getenv(
            "OPTION_SETTLEMENT", "USDT"
        ),
        expiry_policy=os.getenv(
            "OPTION_EXPIRY_POLICY", "NEAREST_ELIGIBLE"
        ),
        order_quantity=os.getenv("ORDER_QUANTITY", "1"),
    )

from nautilus_trader.adapters.bybit import (
    BybitDataClientConfig,
    BybitDataClientFactory,
    BybitEnvironment,
    BybitProductType,
)
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId


def build_bybit_data_node():
    """Build a public Bybit Testnet options data node."""

    data_config = BybitDataClientConfig(
        environment=BybitEnvironment.TESTNET,
        product_types=[BybitProductType.OPTION],
    )

    node = (
        LiveNode.builder(
            "BTC-STRADDLE-DATA",
            TraderId("STRADDLE-001"),
            Environment.LIVE,
        )
        .add_data_client(
            "BYBIT",
            BybitDataClientFactory(),
            data_config,
        )
        .build()
    )

    return node
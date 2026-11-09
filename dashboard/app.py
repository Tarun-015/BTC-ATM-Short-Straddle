import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from dashboard.market_view import build_market_view
from src.straddle.simulation_service import (
    close_simulation,
    create_simulation,
    get_simulation,
    list_simulations,
)
from dashboard.data_access import (
    get_portfolio_metrics,
    get_trade_metrics,
    load_dashboard_data,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "straddle.db"

st.set_page_config(
    page_title="BTC ATM Short Straddle",
    page_icon="📊",
    layout="wide",
)

st_autorefresh(interval=5000, key="btc_straddle_dashboard_refresh")

st.title("BTC ATM Short Straddle")
st.caption(
    "Options Trading System | Bybit Testnet Public Market Data"
)

st.sidebar.title("Dashboard Controls")

db_path = st.sidebar.text_input(
    "SQLite database path",
    value=str(DEFAULT_DB_PATH),
)

if st.sidebar.button("Refresh dashboard", use_container_width=True):
    st.rerun()

st.sidebar.divider()

st.sidebar.write("Environment")
st.sidebar.info(
    os.getenv("TRADING_ENV", "TESTNET")
)

st.sidebar.write("Execution mode")
st.sidebar.warning("SIMULATION ONLY")

st.sidebar.write("Order submission")
st.sidebar.error("Disabled")

data = load_dashboard_data(db_path)

if not data["available"]:
    st.error(data["error"])
    st.info(
        "Start the trading engine separately to generate database "
        "records. The dashboard does not start the engine."
    )
    st.stop()

portfolio = get_portfolio_metrics(data)

st.subheader("System Overview")

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Total Trades",
    portfolio["total_trades"],
)

col2.metric(
    "Open Trades",
    portfolio["open_trades"],
)

col3.metric(
    "Recovery Required",
    portfolio["recovery_trades"],
)

col4.metric(
    "Orders Recorded",
    portfolio["total_orders"],
)

sim_col1, sim_col2, sim_col3 = st.columns(3)
sim_col1.metric("Simulated Trades", len(data["simulated_trades"]))
sim_col2.metric("Simulated Orders", len(data["simulated_orders"]))
sim_col3.metric(
    "Simulated Recovery",
    sum(bool(item["recovery_required"]) for item in data["simulated_trades"]),
)

heartbeat = data["heartbeat"]
market_snapshot = data["market_snapshot"]
selected_pair = data["selected_pair"]
market_view = build_market_view(market_snapshot, selected_pair)

status_col1, status_col2, status_col3 = st.columns(3)

status_col1.metric("Database", "Connected")
status_col2.metric(
    "Market Data Worker",
    heartbeat["effective_status"] if heartbeat else "Not started",
)
status_col3.metric(
    "Market Quotes",
    market_view["freshness"],
)

if heartbeat:
    st.caption(
        f"Worker last update: {heartbeat['last_seen']} | "
        f"Details: {heartbeat.get('details') or 'None'}"
    )
else:
    st.caption("Start the market-data worker in a separate terminal.")

st.divider()

overview_tab, trades_tab, orders_tab, events_tab, recovery_tab, simulation_tab = (
    st.tabs([
        "Overview",
        "Trades",
        "Orders",
        "Execution Events",
        "Recovery",
        "Simulation Lab",
    ])
)

with overview_tab:
    st.subheader("Trade State Distribution")

    if data["trades"]:
        state_counts = (
            pd.DataFrame(data["trades"])["state"]
            .value_counts()
            .rename_axis("State")
            .reset_index(name="Count")
        )

        figure = px.bar(
            state_counts,
            x="State",
            y="Count",
            title="Trades by State",
        )

        st.plotly_chart(
            figure,
            use_container_width=True,
        )
    else:
        st.info("No trades have been recorded.")

    st.subheader("Recent Trades")

    if data["trades"]:
        recent_trades = pd.DataFrame(data["trades"])

        visible_columns = [
            column
            for column in [
                "trade_id",
                "state",
                "requested_quantity",
                "recovery_required",
                "recovery_reason",
                "updated_at",
            ]
            if column in recent_trades.columns
        ]

        st.dataframe(
            recent_trades[visible_columns],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Trade history is empty.")

    st.subheader("Live Market Monitor")

    if market_snapshot:
        market_col1, market_col2, market_col3, market_col4 = st.columns(4)
        market_col1.metric(
            "BTC Reference Price",
            f"{market_view['index_price']:,.2f}" if market_view["index_price"] is not None else "Unavailable",
        )
        market_col2.metric("Market Scan", market_view["status"])
        market_col3.metric(
            "Selected ATM Strike",
            f"{selected_pair['strike']:,.2f}" if selected_pair else "Not selected",
        )
        market_col4.metric(
            "Quote Age",
            f"{market_view['age_seconds']:.1f}s" if market_view["age_seconds"] is not None else "Unknown",
        )
        if market_view["freshness"] == "STALE":
            st.error("Market snapshot is stale. Do not use these quotes for an entry decision.")
        elif market_view["freshness"] == "FRESH":
            st.success("Latest market snapshot is fresh.")
        else:
            st.warning("Market snapshot timestamp could not be validated.")

        if market_snapshot.get("reason"):
            st.warning(market_snapshot["reason"])

        if selected_pair:
            st.markdown(
                f"**Expiry:** {selected_pair['expiry']}  |  "
                f"**Settlement:** {selected_pair['settlement']}  |  "
                f"**Scan:** {market_view['status']}"
            )
            call_col, put_col = st.columns(2)
            with call_col:
                st.markdown("#### CALL contract")
                st.code(selected_pair["call_symbol"])
                st.metric("Bid / Ask", f"{selected_pair['call_bid']:g} / {selected_pair['call_ask']:g}")
                st.write(f"Bid size: {selected_pair['call_bid_size']:g} | Ask size: {selected_pair['call_ask_size']:g}")
                if market_view["call_spread"] is not None:
                    st.metric("CALL spread", f"{market_view['call_spread']:g}")
            with put_col:
                st.markdown("#### PUT contract")
                st.code(selected_pair["put_symbol"])
                st.metric("Bid / Ask", f"{selected_pair['put_bid']:g} / {selected_pair['put_ask']:g}")
                st.write(f"Bid size: {selected_pair['put_bid_size']:g} | Ask size: {selected_pair['put_ask_size']:g}")
                if market_view["put_spread"] is not None:
                    st.metric("PUT spread", f"{market_view['put_spread']:g}")

            premium_col1, premium_col2, premium_col3 = st.columns(3)
            premium_col1.metric("Combined Entry Bid", f"{selected_pair['combined_entry_bid']:g}")
            premium_col2.metric("Combined Buyback Ask", f"{selected_pair['combined_buyback_ask']:g}")
            premium_col3.metric(
                "Quote Validity",
                "VALID" if market_view["quote_valid"] else "INVALID",
            )

            st.subheader("Risk Threshold Preview")
            if market_view["risk_preview"] and market_view["freshness"] == "FRESH":
                preview = market_view["risk_preview"]
                risk_col1, risk_col2, risk_col3 = st.columns(3)
                risk_col1.metric("Reference Entry Premium", f"{preview['entry_premium']:g}")
                risk_col2.metric("Take-profit Buyback", f"{preview['take_profit_cost']:g}")
                risk_col3.metric("Stop-loss Buyback", f"{preview['stop_loss_cost']:g}")
                st.caption(
                    "Preview only: thresholds use the current combined bid as a hypothetical "
                    "entry premium. They are not attached to an open trade and exclude fees/slippage."
                )
            else:
                st.info("Risk preview unavailable until a fresh, valid CALL/PUT pair is recorded.")

            if market_view["freshness"] != "FRESH" or not market_view["quote_valid"]:
                st.error("Entry is not eligible from this dashboard snapshot.")
            else:
                st.info("Market pair is available for review. Trade execution remains simulation-only and is not triggered by this dashboard.")
        else:
            st.warning("NO TRADE: no eligible CALL/PUT pair was found. No entry should be opened.")
    else:
        st.info("No market snapshots yet. Start the market-data worker in a separate terminal.")

with trades_tab:
    st.subheader("Trade History")

    if data["trades"]:
        trade_ids = [
            trade["trade_id"]
            for trade in data["trades"]
        ]

        selected_trade_id = st.selectbox(
            "Select trade",
            trade_ids,
        )

        selected_trade = next(
            trade for trade in data["trades"]
            if trade["trade_id"] == selected_trade_id
        )

        metrics = get_trade_metrics(
            selected_trade_id,
            data["legs"],
            data["orders"],
            data["events"],
        )

        st.write("Trade ID:", selected_trade_id)
        st.write("State:", selected_trade["state"])

        trade_col1, trade_col2, trade_col3, trade_col4 = (
            st.columns(4)
        )

        trade_col1.metric(
            "Requested Quantity",
            selected_trade["requested_quantity"],
        )

        trade_col2.metric(
            "Entry Filled Quantity",
            f"{metrics['entry_filled_quantity']:g}",
        )

        trade_col3.metric(
            "Exit Filled Quantity",
            f"{metrics['exit_filled_quantity']:g}",
        )

        trade_col4.metric(
            "Execution Events",
            metrics["event_count"],
        )

        st.subheader("Option Legs")

        selected_legs = [
            leg for leg in data["legs"]
            if leg["trade_id"] == selected_trade_id
        ]

        if selected_legs:
            st.dataframe(
                pd.DataFrame(selected_legs),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No leg records found.")

        st.subheader("Trade Exposure")

        if metrics["exposed_legs"]:
            st.warning(
                "Outstanding exposure: "
                + ", ".join(metrics["exposed_legs"])
            )
        else:
            st.success("No outstanding exposure recorded.")

        st.subheader("Orders for Selected Trade")

        selected_orders = [
            order for order in data["orders"]
            if order["trade_id"] == selected_trade_id
        ]

        if selected_orders:
            st.dataframe(
                pd.DataFrame(selected_orders),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No orders recorded for this trade.")

        st.subheader("Profit and Loss")

        st.info(
            "P&L is not calculated in this dashboard. Contract "
            "multipliers, complete fill accounting, fees and slippage "
            "are not sufficiently persisted for a reliable result."
        )

    else:
        st.info("No engine trades available.")

    st.subheader("Simulation Trade History")
    if data["simulated_trades"]:
        st.dataframe(
            pd.DataFrame(data["simulated_trades"]),
            use_container_width=True,
            hide_index=True,
        )
        simulation_ids = [item["trade_id"] for item in data["simulated_trades"]]
        selected_sim_trade = st.selectbox(
            "Inspect simulation trade",
            simulation_ids,
            key="trades_simulation_selector",
        )
        sim_legs = [
            item for item in data["simulated_legs"]
            if item["trade_id"] == selected_sim_trade
        ]
        sim_orders = [
            item for item in data["simulated_orders"]
            if item["trade_id"] == selected_sim_trade
        ]
        sim_events = [
            item for item in data["simulated_events"]
            if item["trade_id"] == selected_sim_trade
        ]
        st.caption("All records below are simulated and were never sent to an exchange.")
        st.dataframe(pd.DataFrame(sim_legs), use_container_width=True, hide_index=True)
        st.write("Simulated orders")
        st.dataframe(pd.DataFrame(sim_orders), use_container_width=True, hide_index=True)
        st.write("Simulated execution events")
        st.dataframe(pd.DataFrame(sim_events), use_container_width=True, hide_index=True)
    else:
        st.info("No simulated trades yet. Create one in Simulation Lab.")

with orders_tab:
    st.subheader("Order History")

    if data["orders"]:
        orders_frame = pd.DataFrame(data["orders"])

        status_counts = (
            orders_frame["status"]
            .value_counts()
            .rename_axis("Status")
            .reset_index(name="Count")
        )

        figure = px.bar(
            status_counts,
            x="Status",
            y="Count",
            title="Orders by Status",
        )

        st.plotly_chart(
            figure,
            use_container_width=True,
        )

        st.dataframe(
            orders_frame,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No engine orders recorded.")

    st.subheader("Simulated Orders")
    if data["simulated_orders"]:
        sim_orders_frame = pd.DataFrame(data["simulated_orders"])
        sim_orders_frame.insert(0, "source", "SIMULATION")
        st.dataframe(sim_orders_frame, use_container_width=True, hide_index=True)
    else:
        st.info("No simulated orders recorded.")

with events_tab:
    st.subheader("Execution Event History")

    if data["events"]:
        events_frame = pd.DataFrame(data["events"])

        st.dataframe(
            events_frame,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No engine execution events recorded.")

    st.subheader("Simulated Execution Events")
    if data["simulated_events"]:
        sim_events_frame = pd.DataFrame(data["simulated_events"])
        sim_events_frame.insert(0, "source", "SIMULATION")
        st.dataframe(sim_events_frame, use_container_width=True, hide_index=True)
    else:
        st.info("No simulated execution events recorded.")

with recovery_tab:
    st.subheader("Recovery Monitoring")

    recovery_trades = [
        trade for trade in data["trades"]
        if bool(trade.get("recovery_required", 0))
    ]

    exposed_trade_ids = set()

    for leg in data["legs"]:
        if (
            float(leg["entry_filled_quantity"])
            > float(leg["exit_filled_quantity"])
        ):
            exposed_trade_ids.add(leg["trade_id"])

    if recovery_trades or exposed_trade_ids:
        recovery_ids = {
            trade["trade_id"]
            for trade in recovery_trades
        } | exposed_trade_ids

        recovery_rows = [
            trade for trade in data["trades"]
            if trade["trade_id"] in recovery_ids
        ]

        st.warning(
            f"{len(recovery_ids)} trade(s) require exposure review."
        )

        st.dataframe(
            pd.DataFrame(recovery_rows),
            use_container_width=True,
            hide_index=True,
        )

        for trade_id in sorted(recovery_ids):
            metrics = get_trade_metrics(
                trade_id,
                data["legs"],
                data["orders"],
                data["events"],
            )

            st.write(f"Trade: {trade_id}")
            st.write(
                "Outstanding legs:",
                ", ".join(metrics["exposed_legs"]) or "None",
            )

        st.error(
            "This dashboard is read-only. Recovery execution and "
            "exchange reconciliation are not implemented."
        )
    else:
        st.success("No engine recovery flags or open leg exposure.")

    st.subheader("Simulation Recovery")
    simulated_recovery = [
        item for item in data["simulated_trades"]
        if bool(item.get("recovery_required", 0))
        or item.get("state") in {"PARTIALLY_FILLED", "RECOVERY_REQUIRED"}
    ]
    if simulated_recovery:
        st.warning(f"{len(simulated_recovery)} simulated position(s) need review.")
        st.dataframe(
            pd.DataFrame(simulated_recovery),
            use_container_width=True,
            hide_index=True,
        )
        for item in simulated_recovery:
            outstanding = [
                leg for leg in data["simulated_legs"]
                if leg["trade_id"] == item["trade_id"]
                and float(leg["entry_filled_quantity"]) > float(leg["exit_filled_quantity"])
            ]
            st.write(
                f"{item['trade_id']}: "
                + (", ".join(leg["leg"] for leg in outstanding) or "No outstanding leg quantity")
            )
    else:
        st.success("No simulated recovery cases.")

with simulation_tab:
    st.subheader("Simulation Control Panel")
    st.warning(
        "SIMULATION ONLY. These controls write simulated records to SQLite. "
        "They never connect to an execution client or submit exchange orders."
    )

    st.markdown("#### Simulate short-straddle entry")
    with st.form("simulation_entry_form"):
        entry_quantity = st.number_input(
            "Requested quantity per leg",
            min_value=0.0001,
            value=0.01,
            step=0.01,
            format="%.4f",
        )
        entry_mode = st.selectbox(
            "Entry scenario",
            [
                "BOTH_FULL",
                "CALL_ONLY",
                "PUT_ONLY",
                "PARTIAL_BOTH",
            ],
            format_func=lambda value: {
                "BOTH_FULL": "SELL CALL + SELL PUT — full fills",
                "CALL_ONLY": "SELL CALL only — test unhedged entry",
                "PUT_ONLY": "SELL PUT only — test unhedged entry",
                "PARTIAL_BOTH": "SELL both — partial fills",
            }[value],
        )
        create_clicked = st.form_submit_button(
            "Create simulated entry",
            use_container_width=True,
        )

    if create_clicked:
        try:
            created = create_simulation(
                db_path,
                quantity=str(entry_quantity),
                entry_mode=entry_mode,
            )
            st.success(
                f"Simulation created: {created['trade']['trade_id']} | "
                f"State: {created['trade']['state']}"
            )
        except (ValueError, OSError) as exc:
            st.error(f"Simulation entry rejected: {exc}")

    simulations = list_simulations(db_path)
    if simulations:
        st.markdown("#### Simulated positions")
        st.dataframe(
            pd.DataFrame(simulations),
            use_container_width=True,
            hide_index=True,
        )

        active_simulations = [
            item for item in simulations
            if item["state"] != "CLOSED"
        ]

        if active_simulations:
            st.markdown("#### Simulate buy-to-close / recovery")
            simulation_labels = {
                item["trade_id"]: f"{item['trade_id']} — {item['state']}"
                for item in active_simulations
            }
            with st.form("simulation_exit_form"):
                selected_simulation_id = st.selectbox(
                    "Simulation to close",
                    list(simulation_labels),
                    format_func=lambda value: simulation_labels[value],
                )
                exit_mode = st.selectbox(
                    "Exit scenario",
                    [
                        "BOTH_FULL",
                        "CALL_ONLY",
                        "PUT_ONLY",
                        "PARTIAL_BOTH",
                        "LIQUIDITY_FAILURE",
                    ],
                    format_func=lambda value: {
                        "BOTH_FULL": "BUY CALL + BUY PUT — close all exposure",
                        "CALL_ONLY": "BUY CALL only — leave PUT exposure",
                        "PUT_ONLY": "BUY PUT only — leave CALL exposure",
                        "PARTIAL_BOTH": "Buy back half of each exposed leg",
                        "LIQUIDITY_FAILURE": "Inject insufficient-liquidity failure",
                    }[value],
                )
                close_clicked = st.form_submit_button(
                    "Run simulated exit",
                    use_container_width=True,
                )

            if close_clicked:
                try:
                    closed = close_simulation(
                        db_path,
                        selected_simulation_id,
                        close_mode=exit_mode,
                    )
                    st.success(
                        f"Exit scenario completed. State: "
                        f"{closed['trade']['state']}"
                    )
                    if closed["trade"].get("recovery_reason"):
                        st.warning(closed["trade"]["recovery_reason"])
                except (ValueError, OSError) as exc:
                    st.error(f"Simulation exit rejected: {exc}")

        selected_detail_id = st.selectbox(
            "Inspect simulated trade",
            [item["trade_id"] for item in simulations],
            key="simulation_detail_id",
        )
        detail = get_simulation(db_path, selected_detail_id)
        if detail:
            st.markdown("#### Simulated leg state")
            st.dataframe(
                pd.DataFrame(detail["legs"]),
                use_container_width=True,
                hide_index=True,
            )
            st.markdown("#### Simulated orders")
            if detail["orders"]:
                st.dataframe(
                    pd.DataFrame(detail["orders"]),
                    use_container_width=True,
                    hide_index=True,
                )
            st.markdown("#### Simulated execution events")
            if detail["events"]:
                st.dataframe(
                    pd.DataFrame(detail["events"]),
                    use_container_width=True,
                    hide_index=True,
                )
    else:
        st.info(
            "No simulation trades yet. Start the market-data worker and wait for "
            "a fresh PAIR_FOUND snapshot before creating a simulated entry. "
            "NO_TRADE or stale quotes correctly block simulation."
        )

    st.caption(
        "Simulation fills use the latest persisted bid for SELL and ask for BUY. "
        "Quotes must be fresh and the option symbols must match the original trade. "
        "P&L and fee accounting are reserved for P12."
    )

st.divider()

st.caption(
    "BTC ATM Short Straddle | Auto-refresh: 5 seconds | "
    "Public Testnet market data | Simulation-only execution"
)
"""
FOREX AI TERMINAL
Professional MT5 market-data dashboard
Version: 1.0.0

Safety:
- Market data and account metadata only.
- No order placement or trade modification.
- Uses closed candles (skips the currently forming candle).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ============================================================================
# PAGE CONFIGURATION AND THEME
# ============================================================================

st.set_page_config(
    page_title="Forex AI Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_TITLE = "FOREX AI TERMINAL"
APP_VERSION = "1.0.0"
CANDLE_COUNT = 250

PAIR_CANDIDATES = {
    "EUR/USD": ["EURUSDm", "EURUSD", "EURUSD.a", "EURUSDpro"],
    "XAU/USD": ["XAUUSDm", "XAUUSD", "GOLD", "XAUUSD.a", "GOLDm"],
}

TIMEFRAME_MAP = {
    "D1": mt5.TIMEFRAME_D1,
    "H4": mt5.TIMEFRAME_H4,
    "M30": mt5.TIMEFRAME_M30,
}

PRICE_DIGITS = {
    "EUR/USD": 5,
    "XAU/USD": 3,
}

st.markdown(
    """
    <style>
    :root {
        color-scheme: dark;
    }
    .stApp {
        background: #0b1120;
        color: #e5e7eb;
    }
    [data-testid="stHeader"] {
        background: rgba(11, 17, 32, 0.92);
    }
    [data-testid="stSidebar"] {
        background: #101a2b;
        border-right: 1px solid #263650;
    }
    [data-testid="stMetric"] {
        background: #111c30;
        border: 1px solid #263650;
        border-radius: 12px;
        padding: 16px;
    }
    [data-testid="stMetricLabel"] {
        color: #94a3b8;
    }
    [data-testid="stMetricValue"] {
        color: #f8fafc;
    }
    h1, h2, h3 {
        color: #f1f5f9;
    }
    .hero {
        padding: 18px 22px;
        border: 1px solid #263650;
        border-radius: 16px;
        background: linear-gradient(120deg, #111c30, #14243b);
        margin-bottom: 16px;
    }
    .hero-title {
        font-size: 30px;
        font-weight: 800;
        letter-spacing: 0.4px;
        color: #f8fafc;
    }
    .hero-subtitle {
        color: #9fb0c8;
        font-size: 14px;
        margin-top: 6px;
    }
    .small-note {
        color: #94a3b8;
        font-size: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def initialize_mt5() -> tuple[bool, str]:
    """
    Initialize the locally installed MT5 terminal.
    Returns (success, message).
    """
    try:
        if mt5.initialize():
            return True, "MT5 connection successful"
        return False, f"MT5 initialize failed: {mt5.last_error()}"
    except Exception as exc:
        return False, f"MT5 initialization error: {type(exc).__name__}: {exc}"


def find_broker_symbol(symbol: str) -> tuple[Optional[str], str]:
    """
    Select the first known symbol candidate available in the user's MT5 terminal.
    If common candidates fail, search broker symbols for a matching instrument.
    """
    candidates = PAIR_CANDIDATES.get(symbol, [])
    for candidate in candidates:
        try:
            if mt5.symbol_select(candidate, True):
                return candidate, f"Selected broker symbol: {candidate}"
        except Exception:
            continue

    try:
        all_symbols = mt5.symbols_get()
    except Exception as exc:
        return None, f"Could not list broker symbols: {exc}"

    if not all_symbols:
        return None, (
            f"No symbol list returned for {symbol}. "
            "Open MT5 and check Market Watch."
        )

    names = [item.name for item in all_symbols]
    if symbol == "EUR/USD":
        matches = [
            name for name in names
            if "EURUSD" in name.upper()
        ]
    elif symbol == "XAU/USD":
        matches = [
            name for name in names
            if "XAUUSD" in name.upper() or "GOLD" in name.upper()
        ]
    else:
        matches = []

    if not matches:
        return None, (
            f"No broker symbol matched {symbol}. "
            "Please check the exact instrument name in MT5 Market Watch."
        )

    # Prefer the shortest matching name, which is often the base symbol.
    matches.sort(key=lambda name: (len(name), name))
    for candidate in matches:
        try:
            if mt5.symbol_select(candidate, True):
                return candidate, f"Selected broker symbol: {candidate}"
        except Exception:
            continue

    return None, f"Found possible symbols but could not select any: {matches[:10]}"


def load_closed_candles(
    symbol: str,
    timeframe: int,
    count: int = CANDLE_COUNT,
) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Fetch candles starting at position 1, skipping the still-forming candle.
    Returns a DataFrame and an optional error message.
    """
    try:
        raw_rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, count)
        if raw_rates is None:
            return None, f"MT5 returned no rates: {mt5.last_error()}"
        if len(raw_rates) == 0:
            return None, "No candles were returned. Check symbol and timeframe."

        frame = pd.DataFrame(raw_rates)
        required = {"time", "open", "high", "low", "close"}
        missing = required.difference(frame.columns)
        if missing:
            return None, f"Market data is missing required fields: {sorted(missing)}"

        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.sort_values("time").drop_duplicates("time").reset_index(drop=True)

        if frame.empty:
            return None, "The returned market-data table is empty."

        return frame, None
    except Exception as exc:
        return None, f"Market-data error: {type(exc).__name__}: {exc}"


def format_price(value: float, symbol: str) -> str:
    """Format price using a practical display precision for the selected pair."""
    digits = PRICE_DIGITS.get(symbol, 5)
    return f"{float(value):,.{digits}f}"

def make_candlestick_chart(
    frame: pd.DataFrame,
    pair_label: str,
    symbol: str,
    timeframe_label: str,
) -> go.Figure:
    """Build the dark-theme candlestick chart."""
    figure = go.Figure(
        data=[
            go.Candlestick(
                x=frame["time"],
                open=frame["open"],
                high=frame["high"],
                low=frame["low"],
                close=frame["close"],
                name=symbol,
                increasing_line_color="#22c55e",
                decreasing_line_color="#ef4444",
                increasing_fillcolor="#22c55e",
                decreasing_fillcolor="#ef4444",
            )
        ]
    )
    figure.update_layout(
        template="plotly_dark",
        title=f"{symbol} ({symbol})  |  {timeframe}",
        height=540,
        xaxis_rangeslider_visible=False,
        margin=dict(l=18, r=18, t=62, b=18),
        paper_bgcolor="#0b1120",
        plot_bgcolor="#0b1120",
        font=dict(color="#e5e7eb"),
        xaxis=dict(
            showgrid=True,
            gridcolor="#1f2b40",
            zeroline=False,
            title="Time (UTC)",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#1f2b40",
            zeroline=False,
            title="Price",
            side="right",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return figure


def get_account_snapshot() -> dict:
    """Read limited account metadata; never requests or changes a trade."""
    try:
        info = mt5.account_info()
        if info is None:
            return {}
        return {
            "server": getattr(info, "server", "Unknown"),
            "currency": getattr(info, "currency", "Unknown"),
            "login": getattr(info, "login", None),
            "trade_allowed": getattr(info, "trade_allowed", None),
        }
    except Exception:
        return {}


# ============================================================================
# HEADER
# ============================================================================

st.markdown(
    f"""
    <div class="hero">
        <div class="hero-title">⚡ {APP_TITLE}</div>
        <div class="hero-subtitle">
            Exness MT5 · Multi-timeframe market data · Analysis-only development build · v{APP_VERSION}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================================
# SIDEBAR CONTROLS
# ============================================================================


with st.sidebar:
    st.header("Control Center")

    symbol = st.selectbox(
        "Trading Instrument",
        ["EUR/USD", "XAU/USD"],
        key="trading_instrument",
    )

    timeframe = st.selectbox(
        "Chart Timeframe",
        ["D1", "H4", "M30"],
        key="chart_timeframe",
    )

    candle_count = st.select_slider(
        "Candles to display",
        options=[50, 100, 150, 200, 250, 500],
        value=250,
        key="candle_count_selector",
    )

    refresh_clicked = st.button(
        "↻ Refresh Market Data",
        use_container_width=True,
        key="refresh_market_data_main",
    )

    st.divider()


    st.divider()
    st.subheader("Safety Status")
    st.success("Analysis-only mode")
    st.warning("Automatic orders are disabled.")
    st.caption(
        "This application does not place, modify, or close trades. "
        "Market analysis is not a guarantee of future results."
    )

    st.divider()
    st.subheader("Build Status")
    st.write("Market data: MT5 terminal")
    st.write("Strategy: analysis module not connected to order execution")
    st.write("Risk engine: pending backtesting validation")


if refresh_clicked:
    st.session_state["last_refresh_utc"] = utc_now()

    symbol = symbol
timeframe = timeframe


# ============================================================================
# MT5 CONNECTION AND DATA RETRIEVAL
# ============================================================================

connected = False
connection_message = ""
selected_symbol: Optional[str] = None
data_frame: Optional[pd.DataFrame] = None
data_error: Optional[str] = None
account_snapshot: dict = {}

try:
    connected, connection_message = initialize_mt5()

    if connected:   
        account_snapshot = get_account_snapshot()
        selected_symbol, symbol_message = find_broker_symbol(symbol)

        if selected_symbol is None:
            data_error = symbol_message
        else:
            data_frame, data_error = load_closed_candles(
                selected_symbol,
                TIMEFRAME_MAP[timeframe],
                int(candle_count),
            )
finally:
    # The dashboard only reads data. Shut down its MT5 API session after retrieval.
    try:
        mt5.shutdown()
    except Exception:
        pass


# ============================================================================
# CONNECTION STATUS
# ============================================================================

status_col, server_col, currency_col, refresh_col = st.columns([1.2, 1.5, 1, 1.2])

with status_col:
    if connected:
        st.success("MT5 connected")
    else:
        st.error("MT5 disconnected")

with server_col:
    st.metric("Broker server", str(account_snapshot.get("server", "Unavailable")))

with currency_col:
    st.metric("Account currency", str(account_snapshot.get("currency", "—")))

with refresh_col:
    last_refresh = st.session_state.get("last_refresh_utc", utc_now())
    st.metric("Dashboard refresh", last_refresh.strftime("%H:%M:%S UTC"))


# ============================================================================
# MARKET OVERVIEW AND CHART
# ============================================================================

st.subheader("Market Overview")

if not connected:
    st.error(connection_message or "Could not connect to the MT5 terminal.")
    st.info(
        "Open the Exness MT5 desktop terminal, sign in to the intended demo account, "
        "and make sure Market Watch shows the desired instruments. Then refresh this page."
    )
elif data_error:
    st.error(data_error)
    st.info(
        "The broker may use a different symbol suffix, or historical data may not yet "
        "be loaded. Check the exact symbol in MT5 Market Watch and open its chart once."
    )
elif data_frame is not None and not data_frame.empty:
    df = data_frame
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) >= 2 else latest

    last_close = float(latest["close"])
    previous_close = float(previous["close"])
    absolute_change = last_close - previous_close
    percentage_change = (
        (absolute_change / previous_close) * 100.0
        if previous_close != 0
        else 0.0
    )


    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("Instrument", symbol)
    metric_b.metric("Last closed price", format_price(last_close, symbol))
    metric_c.metric(
        "Previous candle change",
        format_price(absolute_change, symbol),
        f"{percentage_change:+.3f}%",
    )
    metric_d.metric("Closed candles loaded", f"{len(df):,}")

    st.plotly_chart(
        make_candlestick_chart(df, symbol, selected_symbol or symbol, timeframe),
        use_container_width=True,
        key="main_market_candlestick_chart",
    )

    # Market snapshot table
    st.subheader("Recent Closed Candles")
    table_columns = ["time", "open", "high", "low", "close"]
    if "tick_volume" in df.columns:
        table_columns.append("tick_volume")

    recent = df[table_columns].tail(10).copy()
    recent["time"] = recent["time"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    for column in ["open", "high", "low", "close"]:
        recent[column] = recent[column].map(lambda value: format_price(value, symbol))

    st.dataframe(
        recent,
        use_container_width=True,
        hide_index=True,
        key="recent_closed_candles_table",
    )

    # Basic descriptive statistics, not a trading signal
    st.subheader("Descriptive Market Statistics")
    stat_a, stat_b, stat_c = st.columns(3)
    stat_a.metric("Highest high in displayed data", format_price(df["high"].max(), symbol))
    stat_b.metric("Lowest low in displayed data", format_price(df["low"].min(), symbol))
    stat_c.metric(
        "Displayed range",
        format_price(float(df["high"].max() - df["low"].min()), symbol),
    )

    st.caption(
        f"Broker symbol: {selected_symbol} · "
        f"Latest candle time: {latest['time'].strftime('%Y-%m-%d %H:%M UTC')} · "
        "The current forming candle is excluded."
    )
else:
    st.info("No market data is available yet. Check the connection and refresh.")


# ============================================================================
# STRATEGY / SAFETY PANELS
# ============================================================================

st.divider()
st.subheader("System Modules")

module_a, module_b, module_c = st.columns(3)

with module_a:
    st.markdown("### 01 · Market Data")
    st.write("MT5 connectivity, symbol lookup, closed-candle retrieval, and chart display.")
    if connected and data_frame is not None and not data_frame.empty:
        st.success("Data retrieval passed")
    elif connected:
        st.warning("Connected; data needs attention")
    else:
        st.info("Waiting for MT5 connection")

with module_b:
    st.markdown("### 02 · Strategy Engine")
    st.write("ICT/SMC concepts must be defined as explicit, testable rules before signals are trusted.")
    st.info("Analysis only; no orders")

with module_c:
    st.markdown("### 03 · Risk & Backtesting")
    st.write("Historical validation, transaction costs, drawdown controls, and position sizing.")
    st.info("Required before demo execution")


# ============================================================================
# DEVELOPMENT CHECKLIST
# ============================================================================

with st.expander("Development checklist", expanded=False):
    st.markdown(
        """
        - [x] MT5 data connection attempt
        - [x] Broker symbol candidate lookup
        - [x] Closed-candle retrieval
        - [x] Candlestick chart and recent-candle table
        - [x] Unique keys for interactive Streamlit widgets
        - [x] Analysis-only safety design
        - [ ] Formal strategy definitions and unit tests
        - [ ] Historical backtesting with spread, commission, and slippage
        - [ ] Walk-forward validation and out-of-sample reporting
        - [ ] Risk engine tests and demo-only order execution
        - [ ] Monitoring, logging, and recovery tests
        """
    )

st.caption(
    "Forex AI Terminal · Development build · "
    "No automatic orders are sent by this application. "
    "Past performance and analytical indicators do not guarantee future results."
)

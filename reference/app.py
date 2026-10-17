from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


# ============================================================
# Forex AI Terminal Pro — Streamlit prototype
# Analysis-only: this file never submits trading orders.
# ============================================================

st.set_page_config(
    page_title="Forex AI Terminal Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

TIMEFRAMES = {
    "M1": "TIMEFRAME_M1", "M2": "TIMEFRAME_M2", "M3": "TIMEFRAME_M3",
    "M4": "TIMEFRAME_M4", "M5": "TIMEFRAME_M5", "M6": "TIMEFRAME_M6",
    "M10": "TIMEFRAME_M10", "M12": "TIMEFRAME_M12", "M15": "TIMEFRAME_M15",
    "M20": "TIMEFRAME_M20", "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1",
    "H2": "TIMEFRAME_H2", "H3": "TIMEFRAME_H3", "H4": "TIMEFRAME_H4",
    "H6": "TIMEFRAME_H6", "H8": "TIMEFRAME_H8", "H12": "TIMEFRAME_H12",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1", "MN1": "TIMEFRAME_MN1",
}

PAIR_LABELS = {
    "EUR/USD": "EURUSD", "XAU/USD": "XAUUSD", "GBP/USD": "GBPUSD",
    "USD/JPY": "USDJPY", "AUD/USD": "AUDUSD", "USD/CAD": "USDCAD",
    "USD/CHF": "USDCHF", "NZD/USD": "NZDUSD", "XAG/USD": "XAGUSD",
    "BTC/USD": "BTCUSD", "ETH/USD": "ETHUSD",
}

st.markdown(
    """
    <style>
    .stApp { background:#08111f; color:#eaf1ff; }
    [data-testid="stSidebar"] { background:#0e1a2c; border-right:1px solid #243650; }
    [data-testid="stMetric"] {
      background:linear-gradient(145deg,#142640,#0e1b2e);
      border:1px solid #263d5d; border-radius:14px; padding:12px;
    }
    [data-testid="stMetricLabel"] { color:#a9c5ed !important; }
    [data-testid="stMetricValue"] { color:#f3f7ff !important; }
    .hero { background:linear-gradient(120deg,#172d4b,#0d192b);
      border:1px solid #2b4262; border-radius:18px; padding:20px 22px; }
    .hero h1 { font-size:clamp(23px,3vw,35px); margin:0; color:#f5f8ff; }
    .hero p { margin:8px 0 0; color:#9fc3f6; font-size:13px; }
    div.stButton > button { min-height:42px; border-radius:10px; font-weight:600; }
    @media(max-width:700px) {
      .block-container { padding:.75rem .6rem 2rem !important; }
      .hero { padding:15px; }
      [data-testid="stMetric"] { padding:8px; }
      [data-testid="stMetricValue"] { font-size:1.1rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def connect_mt5() -> tuple[bool, str]:
    if mt5 is None:
        return False, "MetaTrader5 package is unavailable in this Python environment."
    try:
        if mt5.terminal_info() is not None:
            return True, "Connected to the running MT5 terminal."
        if mt5.initialize():
            return True, "MT5 initialized successfully."
        return False, f"MT5 initialization failed: {mt5.last_error()}"
    except Exception as exc:
        return False, f"MT5 connection error: {exc}"


def get_broker_symbols() -> list[str]:
    if mt5 is None:
        return []
    try:
        return [item.name for item in (mt5.symbols_get() or [])]
    except Exception:
        return []


def resolve_symbol(label: str, broker_symbols: list[str]) -> Optional[str]:
    root = PAIR_LABELS.get(label, label.replace("/", "")).upper()
    matches = [name for name in broker_symbols if name.upper().startswith(root)]
    if not matches:
        return None
    for name in matches:
        if name.upper() == root:
            return name
    # Common suffixes vary by broker/account type; do not assume one.
    return matches[0]


def load_closed_candles(symbol: str, timeframe: str, count: int) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    if mt5 is None:
        return None, "MetaTrader5 package is not installed."
    constant_name = TIMEFRAMES[timeframe]
    timeframe_value = getattr(mt5, constant_name, None)
    if timeframe_value is None:
        return None, f"This MT5 Python package does not expose {timeframe}. Try a commonly supported timeframe."
    try:
        if not mt5.symbol_select(symbol, True):
            return None, f"Could not select broker symbol {symbol}: {mt5.last_error()}"
        rates = mt5.copy_rates_from_pos(symbol, timeframe_value, 0, int(count) + 1)
        if rates is None or len(rates) < 4:
            return None, f"Not enough historical candles for {symbol} ({timeframe}). Check MT5 history and connection."
        frame = pd.DataFrame(rates)
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        # Drop the currently forming candle: signal analysis uses closed candles only.
        frame = frame.iloc[:-1].copy()
        frame.rename(columns={"tick_volume": "volume"}, inplace=True)
        for col in ("open", "high", "low", "close", "volume"):
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["time", "open", "high", "low", "close"]).reset_index(drop=True)
        if frame.empty:
            return None, "No valid closed candles were returned."
        return frame, None
    except Exception as exc:
        return None, f"Historical data error: {exc}"


def add_indicators(frame: pd.DataFrame, ema_fast: int, ema_slow: int, sma_period: int,
                   rsi_period: int, bb_period: int, bb_std: float) -> pd.DataFrame:
    out = frame.copy()
    out["EMA Fast"] = out["close"].ewm(span=ema_fast, adjust=False).mean()
    out["EMA Slow"] = out["close"].ewm(span=ema_slow, adjust=False).mean()
    out["SMA"] = out["close"].rolling(sma_period, min_periods=1).mean()
    delta = out["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / rsi_period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / rsi_period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out["RSI"] = (100 - 100 / (1 + rs)).fillna(50)
    mid = out["close"].rolling(bb_period, min_periods=1).mean()
    sd = out["close"].rolling(bb_period, min_periods=1).std().fillna(0)
    out["BB Mid"] = mid
    out["BB Upper"] = mid + bb_std * sd
    out["BB Lower"] = mid - bb_std * sd
    out["ATR"] = pd.concat([
        out["high"] - out["low"],
        (out["high"] - out["close"].shift()).abs(),
        (out["low"] - out["close"].shift()).abs(),
    ], axis=1).max(axis=1).rolling(14, min_periods=1).mean()
    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["MACD Signal"] = out["MACD"].ewm(span=9, adjust=False).mean()
    return out


def heikin_ashi(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    ha_close = (frame["open"] + frame["high"] + frame["low"] + frame["close"]) / 4
    ha_open = np.zeros(len(frame), dtype=float)
    if len(frame):
        ha_open[0] = (float(frame["open"].iloc[0]) + float(frame["close"].iloc[0])) / 2
    for i in range(1, len(frame)):
        ha_open[i] = (ha_open[i - 1] + ha_close.iloc[i - 1]) / 2
    out["open"], out["close"] = ha_open, ha_close
    out["high"] = pd.concat([frame["high"], out["open"], out["close"]], axis=1).max(axis=1)
    out["low"] = pd.concat([frame["low"], out["open"], out["close"]], axis=1).min(axis=1)
    return out


def price_digits(symbol: str) -> int:
    if mt5 is not None:
        try:
            info = mt5.symbol_info(symbol)
            if info is not None:
                return int(info.digits)
        except Exception:
            pass
    return 3 if ("JPY" in symbol or "XAU" in symbol) else 5


def trend_summary(frame: pd.DataFrame) -> tuple[str, str]:
    last = frame.iloc[-1]
    close = float(last["close"])
    fast = float(last["EMA Fast"])
    slow = float(last["EMA Slow"])
    if close > fast > slow:
        return "BULLISH", "Close is above both moving averages and the fast EMA is above the slow EMA."
    if close < fast < slow:
        return "BEARISH", "Close is below both moving averages and the fast EMA is below the slow EMA."
    return "MIXED", "Price and moving-average alignment are mixed. This is not a trade signal."


def make_chart(frame: pd.DataFrame, display_frame: pd.DataFrame, chart_type: str, theme: str,
               bull: str, bear: str, show_fast: bool, show_slow: bool, show_sma: bool,
               show_bb: bool, show_sr: bool, show_rsi: bool, show_macd: bool,
               show_volume: bool) -> go.Figure:
    subpanels = [name for name, enabled in (("RSI", show_rsi), ("MACD", show_macd), ("Volume", show_volume)) if enabled]
    rows = 1 + len(subpanels)
    heights = [0.66] + [0.34 / len(subpanels)] * len(subpanels) if subpanels else [1.0]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.025,
                        row_heights=heights, subplot_titles=["Price chart"] + subpanels)
    if chart_type == "Line":
        fig.add_trace(go.Scatter(x=display_frame["time"], y=display_frame["close"], mode="lines",
                                 name="Close", line=dict(color="#52A8FF", width=2)), row=1, col=1)
    elif chart_type == "Area":
        fig.add_trace(go.Scatter(x=display_frame["time"], y=display_frame["close"], mode="lines",
                                 name="Close", line=dict(color="#52A8FF", width=2), fill="tozeroy",
                                 fillcolor="rgba(82,168,255,0.12)"), row=1, col=1)
    elif chart_type == "OHLC":
        fig.add_trace(go.Ohlc(x=display_frame["time"], open=display_frame["open"], high=display_frame["high"],
                              low=display_frame["low"], close=display_frame["close"], name="OHLC",
                              increasing_line_color=bull, decreasing_line_color=bear), row=1, col=1)
    else:
        fig.add_trace(go.Candlestick(x=display_frame["time"], open=display_frame["open"], high=display_frame["high"],
                                     low=display_frame["low"], close=display_frame["close"], name=chart_type,
                                     increasing_line_color=bull, increasing_fillcolor=bull,
                                     decreasing_line_color=bear, decreasing_fillcolor=bear), row=1, col=1)
    if show_fast:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["EMA Fast"], name="EMA Fast",
                                 line=dict(color="#FFD166", width=1.4)), row=1, col=1)
    if show_slow:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["EMA Slow"], name="EMA Slow",
                                 line=dict(color="#54B7FF", width=1.4)), row=1, col=1)
    if show_sma:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["SMA"], name="SMA",
                                 line=dict(color="#C084FC", width=1.4)), row=1, col=1)
    if show_bb:
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["BB Upper"], name="BB Upper",
                                 line=dict(color="#6C8EBF", width=1, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=frame["time"], y=frame["BB Lower"], name="BB Lower",
                                 line=dict(color="#6C8EBF", width=1, dash="dot"),
                                 fill="tonexty", fillcolor="rgba(108,142,191,0.06)"), row=1, col=1)
    if show_sr and len(frame) >= 20:
        recent = frame.tail(min(100, len(frame)))
        support = float(recent["low"].min())
        resistance = float(recent["high"].max())
        fig.add_hline(y=support, line_dash="dot", line_color="#20C997",
                      annotation_text=f"Recent support {support:.{price_digits(st.session_state.get('broker_symbol', 'EURUSD'))}f}", row=1, col=1)
        fig.add_hline(y=resistance, line_dash="dot", line_color="#F59E0B",
                      annotation_text=f"Recent resistance {resistance:.{price_digits(st.session_state.get('broker_symbol', 'EURUSD'))}f}", row=1, col=1)
    panel_row = 2
    for panel in subpanels:
        if panel == "RSI":
            fig.add_trace(go.Scatter(x=frame["time"], y=frame["RSI"], name="RSI",
                                     line=dict(color="#C084FC", width=1.4)), row=panel_row, col=1)
            fig.add_hline(y=70, line_dash="dot", line_color=bear, row=panel_row, col=1)
            fig.add_hline(y=30, line_dash="dot", line_color=bull, row=panel_row, col=1)
            fig.update_yaxes(range=[0, 100], row=panel_row, col=1)
        elif panel == "MACD":
            fig.add_trace(go.Scatter(x=frame["time"], y=frame["MACD"], name="MACD",
                                     line=dict(color="#52A8FF", width=1.3)), row=panel_row, col=1)
            fig.add_trace(go.Scatter(x=frame["time"], y=frame["MACD Signal"], name="MACD Signal",
                                     line=dict(color="#F59E0B", width=1.2)), row=panel_row, col=1)
        elif panel == "Volume":
            colors = [bull if c >= o else bear for c, o in zip(frame["close"], frame["open"])]
            fig.add_trace(go.Bar(x=frame["time"], y=frame["volume"], name="Tick volume",
                                 marker_color=colors, opacity=0.7), row=panel_row, col=1)
        panel_row += 1
    if theme == "Light":
        paper, plot, font, grid, template = "#f7f9fc", "#ffffff", "#172033", "#dce3ed", "plotly_white"
    elif theme == "Ocean Blue":
        paper, plot, font, grid, template = "#071827", "#0b2236", "#e8f3ff", "#1b405d", "plotly_dark"
    else:
        paper, plot, font, grid, template = "#080f1d", "#080f1d", "#dbe7fb", "#203149", "plotly_dark"
    fig.update_layout(template=template, paper_bgcolor=paper, plot_bgcolor=plot,
                      font=dict(color=font, size=12), height=650 if rows == 1 else 700,
                      margin=dict(l=8, r=8, t=48, b=10), hovermode="x unified",
                      xaxis_rangeslider_visible=False, dragmode="pan",
                      legend=dict(orientation="h", y=1.02, x=0))
    for row in range(1, rows + 1):
        fig.update_xaxes(showgrid=True, gridcolor=grid, zeroline=False, row=row, col=1)
        fig.update_yaxes(showgrid=True, gridcolor=grid, zeroline=False, side="right", row=row, col=1)
    return fig


# Sidebar: controls are all uniquely keyed to avoid duplicate widget IDs.
with st.sidebar:
    st.markdown("## 🎛️ Control Center")
    instrument = st.selectbox("Instrument", list(PAIR_LABELS), index=0, key="instrument_select")
    timeframe = st.selectbox("Timeframe", list(TIMEFRAMES), index=list(TIMEFRAMES).index("H1"), key="timeframe_select")
    candle_count = st.select_slider("Historical candles", options=[100, 150, 200, 250, 300, 500, 750, 1000],
                                    value=250, key="candle_count_select")
    chart_type = st.selectbox("Chart type", ["Candlesticks", "Heikin-Ashi", "Line", "Area", "OHLC"], key="chart_type_select")
    theme = st.selectbox("Theme", ["Midnight Pro", "Ocean Blue", "Light"], key="theme_select")
    bull_color = st.color_picker("Bullish candle", "#16C784", key="bull_color_select")
    bear_color = st.color_picker("Bearish candle", "#EA3943", key="bear_color_select")
    st.markdown("### Indicators")
    ema_fast_period = st.number_input("Fast EMA period", min_value=2, max_value=300, value=20, key="ema_fast_period")
    ema_slow_period = st.number_input("Slow EMA period", min_value=3, max_value=500, value=50, key="ema_slow_period")
    sma_period = st.number_input("SMA period", min_value=2, max_value=500, value=200, key="sma_period")
    rsi_period = st.number_input("RSI period", min_value=2, max_value=100, value=14, key="rsi_period")
    bb_period = st.number_input("Bollinger period", min_value=2, max_value=200, value=20, key="bb_period")
    bb_std = st.slider("Bollinger deviation", min_value=1.0, max_value=4.0, value=2.0, step=0.25, key="bb_std")
    show_fast = st.checkbox("Show fast EMA", value=True, key="show_fast_ema")
    show_slow = st.checkbox("Show slow EMA", value=True, key="show_slow_ema")
    show_sma = st.checkbox("Show SMA", value=False, key="show_sma")
    show_bb = st.checkbox("Show Bollinger Bands", value=False, key="show_bollinger")
    show_rsi = st.checkbox("Show RSI panel", value=False, key="show_rsi")
    show_macd = st.checkbox("Show MACD panel", value=False, key="show_macd")
    show_volume = st.checkbox("Show tick volume", value=False, key="show_tick_volume")
    show_sr = st.checkbox("Show recent support/resistance", value=True, key="show_sr")
    refresh = st.button("↻ Refresh market data", use_container_width=True, key="refresh_market_data")
    st.divider()
    st.success("Analysis-only mode")
    st.warning("Automatic trading is disabled.")
    st.caption("No orders are sent, modified or closed by this app.")

st.markdown(
    """<div class="hero"><h1>⚡ FOREX AI TERMINAL PRO</h1>
    <p>Exness MT5 data · Interactive charts · Multi-timeframe analysis · Mobile-friendly prototype</p></div>""",
    unsafe_allow_html=True,
)

connected, connection_message = connect_mt5()
if not connected:
    st.error(connection_message)
    st.info("Open the MT5 desktop terminal, log in to your Exness demo account and keep MT5 running.")
    st.stop()

if refresh:
    st.cache_data.clear()

broker_symbols = get_broker_symbols()
broker_symbol = resolve_symbol(instrument, broker_symbols)
if not broker_symbol:
    st.error(f"Could not match {instrument} to a broker symbol. Check Market Watch in MT5.")
    with st.expander("Available broker symbols"):
        st.code(", ".join(broker_symbols[:150]))
    st.stop()
st.session_state["broker_symbol"] = broker_symbol

frame, data_error = load_closed_candles(broker_symbol, timeframe, candle_count)
if data_error or frame is None:
    st.error(data_error or "Market data unavailable.")
    st.stop()

frame = add_indicators(frame, int(ema_fast_period), int(ema_slow_period), int(sma_period),
                       int(rsi_period), int(bb_period), float(bb_std))
display_frame = heikin_ashi(frame) if chart_type == "Heikin-Ashi" else frame
digits = price_digits(broker_symbol)
last_close = float(frame["close"].iloc[-1])
previous_close = float(frame["close"].iloc[-2]) if len(frame) > 1 else last_close
change = last_close - previous_close
pct_change = (change / previous_close * 100) if previous_close else 0.0
bias, bias_explanation = trend_summary(frame)

account = mt5.account_info()
terminal = mt5.terminal_info()
server_name = getattr(account, "server", "Connected") if account else "Unavailable"
account_currency = getattr(account, "currency", "—") if account else "—"

status = st.columns(4)
status[0].success("MT5 connected")
status[1].metric("Broker server", str(server_name))
status[2].metric("Account currency", str(account_currency))
status[3].metric("Updated (UTC)", datetime.now(timezone.utc).strftime("%H:%M:%S"))

st.markdown("## Market overview")
overview = st.columns(4)
overview[0].metric("Instrument", instrument, broker_symbol)
overview[1].metric("Last closed price", f"{last_close:,.{digits}f}")
overview[2].metric("Previous candle change", f"{change:+,.{digits}f}", f"{pct_change:+.3f}%")
overview[3].metric("Closed candles", f"{len(frame):,}", timeframe)

if mt5 is not None:
    tick = mt5.symbol_info_tick(broker_symbol)
    if tick is not None:
        bid, ask = float(tick.bid), float(tick.ask)
        spread = ask - bid
        quotes = st.columns(3)
        quotes[0].metric("Bid", f"{bid:,.{digits}f}")
        quotes[1].metric("Ask", f"{ask:,.{digits}f}")
        quotes[2].metric("Spread (price units)", f"{spread:,.{digits}f}")

st.markdown("## 📊 Interactive chart")
st.caption("On supported devices: drag to pan, pinch/scroll to zoom, use the chart toolbar for crosshair, drawings, reset and export.")
fig = make_chart(frame, display_frame, chart_type, theme, bull_color, bear_color,
                 show_fast, show_slow, show_sma, show_bb, show_sr,
                 show_rsi, show_macd, show_volume)
st.plotly_chart(
    fig, use_container_width=True, key="main_interactive_chart",
    config={
        "responsive": True, "scrollZoom": True, "displaylogo": False,
        "modeBarButtonsToAdd": ["drawline", "drawrect", "drawcircle", "eraseshape"],
        "toImageButtonOptions": {"format": "png", "filename": "forex_ai_terminal_chart", "scale": 2},
    },
)

st.markdown("### Quick timeframe")
quick_cols = st.columns(7)
for i, quick_tf in enumerate(["M5", "M15", "M30", "H1", "H4", "D1", "W1"]):
    if quick_cols[i].button(quick_tf, use_container_width=True, key=f"quick_timeframe_{quick_tf}"):
        st.session_state["timeframe_select"] = quick_tf
        st.rerun()

st.markdown("## Price-action snapshot")
p1, p2, p3 = st.columns(3)
p1.metric("EMA trend clue", bias)
p2.metric(f"RSI ({int(rsi_period)})", f"{float(frame['RSI'].iloc[-1]):.1f}")
p3.metric("EMA structure", "Fast above slow" if frame["EMA Fast"].iloc[-1] > frame["EMA Slow"].iloc[-1] else "Fast below slow")
st.info(bias_explanation)

last = frame.iloc[-1]
body = abs(float(last["close"]) - float(last["open"]))
candle_range = max(float(last["high"]) - float(last["low"]), 1e-12)
upper_wick = float(last["high"]) - max(float(last["open"]), float(last["close"]))
lower_wick = min(float(last["open"]), float(last["close"])) - float(last["low"])
candle_text = "Bullish candle" if last["close"] > last["open"] else ("Bearish candle" if last["close"] < last["open"] else "Doji-like candle")
if body / candle_range < 0.1:
    candle_text = "Small-body / indecision candle"
elif lower_wick / candle_range > 0.55:
    candle_text += " with a long lower wick"
elif upper_wick / candle_range > 0.55:
    candle_text += " with a long upper wick"
st.write(f"**Latest closed candle:** {candle_text}.")
st.caption("Trend and candle descriptions are educational observations, not guaranteed entry or exit signals.")

with st.expander("Recent closed candles"):
    recent = frame.tail(25).copy()
    recent["time"] = recent["time"].dt.strftime("%Y-%m-%d %H:%M UTC")
    st.dataframe(recent.iloc[::-1][["time", "open", "high", "low", "close", "volume"]],
                 use_container_width=True, hide_index=True)

with st.expander("Connection and limitations"):
    st.write(f"Broker symbol: `{broker_symbol}`")
    st.write(f"Selected timeframe: `{timeframe}`")
    st.write(f"Terminal status: {'Available' if terminal is not None else 'Check terminal'}")
    st.write("This prototype reads data from the running Windows MT5 terminal. Some timeframes depend on broker history and MT5 build.")
    st.write("This file does not implement a complete ICT/SMC engine, a validated backtester, or order execution. Those must be separate, tested modules.")

st.caption("Forex AI Terminal Pro · Local prototype · Historical prices and demo results do not guarantee future performance.")

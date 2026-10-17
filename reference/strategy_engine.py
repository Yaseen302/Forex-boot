
import MetaTrader5 as mt5
import pandas as pd

PAIRS = {
    "EUR/USD": "EURUSDm",
    "XAU/USD": "XAUUSDm",
}

TIMEFRAMES = {
    "D1": mt5.TIMEFRAME_D1,
    "H4": mt5.TIMEFRAME_H4,
    "M30": mt5.TIMEFRAME_M30,
}

BARS = 300
PIVOT_WINDOW = 2


def find_swings(df):
    highs = []
    lows = []

    w = PIVOT_WINDOW

    for i in range(w, len(df) - w):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]

        previous_highs = df["high"].iloc[i-w:i]
        next_highs = df["high"].iloc[i+1:i+w+1]

        previous_lows = df["low"].iloc[i-w:i]
        next_lows = df["low"].iloc[i+1:i+w+1]

        if high > previous_highs.max() and high > next_highs.max():
            highs.append((i, float(high)))

        if low < previous_lows.min() and low < next_lows.min():
            lows.append((i, float(low)))

    return highs, lows


def detect_fvg(df):
    found = []

    # Three-candle Fair Value Gap approximation.
    for i in range(2, len(df)):
        first = df.iloc[i - 2]
        third = df.iloc[i]

        if third["low"] > first["high"]:
            found.append({
                "type": "Bullish FVG",
                "lower": float(first["high"]),
                "upper": float(third["low"]),
                "time": third["time"],
            })

        elif third["high"] < first["low"]:
            found.append({
                "type": "Bearish FVG",
                "lower": float(third["high"]),
                "upper": float(first["low"]),
                "time": third["time"],
            })

    return found


def analyze(df):
    if len(df) < 30:
        return {"error": "Not enough candles"}

    swing_highs, swing_lows = find_swings(df)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"error": "Not enough confirmed swing points"}

    last_close = float(df["close"].iloc[-1])
    previous_close = float(df["close"].iloc[-2])

    last_high = swing_highs[-1][1]
    last_low = swing_lows[-1][1]

    old_high = swing_highs[-2][1]
    old_low = swing_lows[-2][1]

    if last_high > old_high and last_low > old_low:
        trend = "Bullish"
    elif last_high < old_high and last_low < old_low:
        trend = "Bearish"
    else:
        trend = "Mixed / unclear"

    event = "No confirmed break"

    if previous_close <= last_high and last_close > last_high:
        event = "Bullish structure break (BOS candidate)"

    elif previous_close >= last_low and last_close < last_low:
        event = "Bearish structure break (BOS candidate)"

    fvg_list = detect_fvg(df)

    latest_fvg = None
    if fvg_list:
        latest_fvg = fvg_list[-1]

    return {
        "close": last_close,
        "trend": trend,
        "structure_event": event,
        "support_candidate": last_low,
        "resistance_candidate": last_high,
        "latest_fvg": latest_fvg,
    }


def main():
    print("=== ICT/SMC INITIAL ANALYSIS ===")
    print("Analysis only - no orders will be placed.")

    if not mt5.initialize():
        print("MT5 connection failed:", mt5.last_error())
        return

    try:
        account = mt5.account_info()

        if account is None:
            print("Account information unavailable.")
            return

        print("Connected server:", account.server)

        for pair, symbol in PAIRS.items():
            print(f"\n{'=' * 40}\n{pair} ({symbol})")

            if not mt5.symbol_select(symbol, True):
                print("Symbol selection failed:", mt5.last_error())
                continue

            for label, timeframe in TIMEFRAMES.items():
                rates = mt5.copy_rates_from_pos(
                    symbol, timeframe, 1, BARS
                )

                print(f"\n--- {label} ---")

                if rates is None or len(rates) == 0:
                    print("Candle data unavailable:", mt5.last_error())
                    continue

                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(
                    df["time"], unit="s", utc=True
                )

                result = analyze(df)

                for key, value in result.items():
                    print(f"{key}: {value}")

        print("\nAnalysis finished. No trades placed.")

    finally:
        mt5.shutdown()          


if __name__ == "__main__":
    main()

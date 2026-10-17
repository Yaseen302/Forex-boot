
import MetaTrader5 as mt5
import pandas as pd

def main():
    print("=== FOREX BOT: CONNECTION & DATA TEST ===")

    if not mt5.initialize():
        print("MT5 initialize failed:", mt5.last_error())
        return

    try:
        account = mt5.account_info()

        if account is None:
            print("Account information unavailable:", mt5.last_error())
            return

        print("Connected to:", account.server)
        print("Account currency:", account.currency)
        print("Trading mode: DATA TEST ONLY - no orders")

        all_symbols = mt5.symbols_get()

        if all_symbols is None:
            print("Could not retrieve symbols:", mt5.last_error())
            return

        names = [item.name for item in all_symbols]
        matches = [
            name for name in names
            if "EURUSD" in name.upper()
        ]

        print("\nEURUSD-related broker symbols:")
        for name in matches:
            print(" -", name)

        if not matches:
            print("\nEURUSD symbol not found.")
            print("Open Market Watch and check available Forex symbols.")
            return

        # Prefer exact EURUSD; otherwise use the first broker variant.
        symbol = next(
            (name for name in matches if name.upper() == "EURUSD"),
            matches[0]
        )

        if not mt5.symbol_select(symbol, True):
            print("Could not select", symbol, mt5.last_error())
            return

        print("\nSelected symbol:", symbol)

        timeframes = {
            "D1": mt5.TIMEFRAME_D1,
            "H4": mt5.TIMEFRAME_H4,
            "M30": mt5.TIMEFRAME_M30,
        }

        for label, timeframe in timeframes.items():
            rates = mt5.copy_rates_from_pos(
                symbol, timeframe, 1, 5
            )

            print(f"\n--- {symbol} | {label} ---")

            if rates is None or len(rates) == 0:
                print("No candle data:", mt5.last_error())
                continue

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(
                df["time"], unit="s", utc=True
            )

            print(
                df[["time", "open", "high", "low", "close"]]
                .to_string(index=False)
            )

        print("\nData test finished. No trades were placed.")

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

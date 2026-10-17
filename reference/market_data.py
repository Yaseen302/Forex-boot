
import MetaTrader5 as mt5
import pandas as pd

TIMEFRAMES = {
    "D1": mt5.TIMEFRAME_D1,
    "H4": mt5.TIMEFRAME_H4,
    "M30": mt5.TIMEFRAME_M30,
}

PAIRS = {
    "EUR/USD": "EURUSD",
    "XAU/USD": "XAUUSD",
}


def main():
    print("=== FOREX BOT: MARKET DATA CHECK ===")

    if not mt5.initialize():
        print("MT5 connection failed:", mt5.last_error())
        return

    try:
        account = mt5.account_info()

        if account is None:
            print("Account unavailable:", mt5.last_error())
            return

        print("Server:", account.server)
        print("Mode: DATA ONLY - NO TRADES")

        available = mt5.symbols_get()

        if available is None:
            print("Cannot read symbols:", mt5.last_error())
            return

        names = [item.name for item in available]

        for pair, base_name in PAIRS.items():
            matches = [
                name for name in names
                if base_name in name.upper()
            ]

            print(f"\n=== {pair} ===")

            if not matches:
                print("Symbol not found. Check broker symbols.")
                continue

            exact = [
                name for name in matches
                if name.upper() == base_name
            ]
            symbol = exact[0] if exact else matches[0]

            print("Broker symbol:", symbol)

            if not mt5.symbol_select(symbol, True):
                print("Cannot select symbol:", mt5.last_error())
                continue

            for tf_name, timeframe in TIMEFRAMES.items():
                rates = mt5.copy_rates_from_pos(
                    symbol, timeframe, 1, 5
                )

                print(f"\n{tf_name} - latest 5 closed candles")

                if rates is None or len(rates) == 0:
                    print("No data:", mt5.last_error())
                    continue

                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(
                    df["time"], unit="s", utc=True
                )

                print(
                    df[["time", "open", "high", "low", "close"]]
                    .to_string(index=False)
                )

        print("\nData check complete. No trades placed.")

    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()

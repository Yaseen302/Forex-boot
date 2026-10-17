
"""ForexBot risk engine.
Calculations only: this module never sends trading orders.
"""

from math import floor, log10, isfinite


def calculate_position_size(
    mt5,
    symbol,
    entry_price,
    stop_loss,
    risk_percent=0.5,
    max_risk_percent=0.5,
    equity=None,
):
    """Calculate a broker-valid volume from the stop-loss distance."""

    try:
        entry = float(entry_price)
        stop = float(stop_loss)
        risk_pct = float(risk_percent)

        if not all(map(isfinite, [entry, stop, risk_pct])):
            raise ValueError("Prices and risk must be finite numbers.")

        if entry <= 0 or stop <= 0:
            raise ValueError("Entry and stop-loss must be positive.")

        if entry == stop:
            raise ValueError("Stop-loss must differ from entry.")

        if risk_pct <= 0 or risk_pct > max_risk_percent:
            raise ValueError(
                f"Risk must be above 0 and at most "
                f"{max_risk_percent}%."
            )

        account = mt5.account_info()
        if account is None:
            raise RuntimeError("Cannot read MT5 account information.")

        available_equity = (
            float(equity) if equity is not None
            else float(account.equity)
        )

        if not isfinite(available_equity) or available_equity <= 0:
            raise ValueError("Account equity must be positive.")

        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Symbol not found: {symbol}")

        tick_size = float(info.trade_tick_size or 0)
        tick_value = float(
            getattr(info, "trade_tick_value_loss", 0)
            or info.trade_tick_value
            or 0
        )

        if tick_size <= 0 or tick_value <= 0:
            raise RuntimeError(
                "Broker tick size/value unavailable; "
                "cannot calculate safe position size."
            )

        stop_distance = abs(entry - stop)
        loss_per_lot = (stop_distance / tick_size) * tick_value

        if not isfinite(loss_per_lot) or loss_per_lot <= 0:
            raise ValueError("Invalid stop-loss risk calculation.")

        risk_amount = available_equity * risk_pct / 100
        raw_volume = risk_amount / loss_per_lot

        volume_min = float(info.volume_min)
        volume_max = float(info.volume_max)
        volume_step = float(info.volume_step)

        if volume_min <= 0 or volume_step <= 0 or volume_max < volume_min:
            raise RuntimeError("Invalid broker volume settings.")

        # Round down: never round volume up beyond the risk budget.
        volume = floor((raw_volume + 1e-12) / volume_step) * volume_step
        volume = round(volume, max(0, -int(log10(volume_step)))
                       if volume_step < 1 else 0)

        # Do not force the broker's minimum lot if it exceeds the risk cap.
        if volume < volume_min:
            return {
                "ok": False,
                "reason": "Minimum broker lot exceeds calculated risk budget.",
                "risk_amount": round(risk_amount, 2),
                "suggested_volume": 0.0,
            }

        volume = min(volume, volume_max)

        return {
            "ok": True,
            "symbol": symbol,
            "entry": entry,
            "stop_loss": stop,
            "stop_distance": stop_distance,
            "equity": round(available_equity, 2),
            "risk_percent": risk_pct,
            "risk_amount": round(risk_amount, 2),
            "estimated_loss": round(volume * loss_per_lot, 2),
            "volume": volume,
            "reason": "Calculation only; no order was sent.",
        }

    except (ValueError, TypeError, RuntimeError, AttributeError) as exc:
        return {"ok": False, "reason": str(exc)}


def daily_loss_guard(
    start_equity,
    current_equity,
    max_daily_loss_percent=2.0,
):
    """Block new entries when the equity-based daily loss limit is reached."""

    try:
        start = float(start_equity)
        current = float(current_equity)
        limit = float(max_daily_loss_percent)

        if not all(map(isfinite, [start, current, limit])):
            raise ValueError("Inputs must be finite numbers.")

        if start <= 0 or current < 0 or limit <= 0 or limit > 100:
            raise ValueError("Invalid equity or daily-loss limit.")

        loss_amount = max(0.0, start - current)
        loss_percent = loss_amount / start * 100
        blocked = loss_percent >= limit

        return {
            "ok": True,
            "trading_allowed": not blocked,
            "start_equity": round(start, 2),
            "current_equity": round(current, 2),
            "loss_amount": round(loss_amount, 2),
            "loss_percent": round(loss_percent, 3),
            "daily_limit_percent": limit,
            "reason": (
                "Daily loss limit reached."
                if blocked else "Daily loss limit not reached."
            ),
        }

    except (ValueError, TypeError) as exc:
        return {
            "ok": False,
            "trading_allowed": False,
            "reason": str(exc),
        }

"""Offline forecasting experiment; never imported by the order/execution path.

Input is chronological *completed* bid OHLC candles. A feature row at closed bar i
uses only bars <= i. Its binary target is whether a hypothetical one-lot LONG from
the next bar's bid open to bar i+horizon's bid close has positive return after the
explicit fixed spread, two-sided slippage, commission and elapsed-time swap.
This is a fixed-horizon forecasting label, NOT the strategy's SL/TP trade result.

No feature/threshold/model search is performed. All scalers and logistic models
fit training rows only. Label horizons are purged before chronological boundaries.
Better scores never promote a model into trading; real data and human review are
required. Joblib files are WRITE-ONLY here: never load an untrusted pickle/model.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import io
import json
import math
from pathlib import Path
import platform
import statistics
from typing import Sequence


FEATURE_NAMES = (
    "return_1", "return_3", "return_6", "return_12", "body_relative",
    "range_relative", "upper_wick_fraction", "lower_wick_fraction",
    "atr_14_relative", "distance_sma_6", "distance_sma_24", "volatility_12",
)
WARMUP = 24
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ResearchCosts:
    """All monetary cost values must use the instrument's quote currency.

    commission_round_trip_per_lot is nonnegative; signed swap_per_lot_day is
    positive for credit or negative for debit. Fixed swap accrues continuously
    with elapsed time. Broker rollover/triple swaps are not simulated.
    """

    point_size: float
    spread_points: float
    slippage_points: float
    commission_round_trip_per_lot: float
    swap_per_lot_day: float
    contract_size: float
    timeframe_minutes: int
    quote_currency: str

    def validate(self) -> None:
        for name in (
            "point_size", "spread_points", "slippage_points",
            "commission_round_trip_per_lot", "swap_per_lot_day", "contract_size",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if self.point_size <= 0 or self.contract_size <= 0:
            raise ValueError("point_size and contract_size must be positive")
        if min(self.spread_points, self.slippage_points, self.commission_round_trip_per_lot) < 0:
            raise ValueError("Spread, slippage and round-trip commission cannot be negative")
        if isinstance(self.timeframe_minutes, bool) or not isinstance(self.timeframe_minutes, int) or self.timeframe_minutes <= 0:
            raise ValueError("timeframe_minutes must be a positive integer")
        if not self.quote_currency.strip() or len(self.quote_currency) > 12:
            raise ValueError("quote_currency must identify the instrument's quote currency")


@dataclass(frozen=True)
class Sample:
    decision_index: int
    decision_time: int
    label_end_index: int
    label_end_time: int
    features: tuple[float, ...]
    target: int
    net_return: float


def validate_candles(candles: Sequence[dict]) -> list[dict]:
    """Strict order and OHLC checks; unknown columns never become features."""
    clean = []
    previous_time = -1
    for index, row in enumerate(candles):
        try:
            raw_time = float(row["time"])
            values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"Candle {index}: expected numeric time,open,high,low,close") from exc
        if not math.isfinite(raw_time) or not raw_time.is_integer() or raw_time < 0:
            raise ValueError(f"Candle {index}: time must be nonnegative integer Unix seconds")
        timestamp = int(raw_time)
        if timestamp <= previous_time:
            raise ValueError(f"Candle {index}: timestamps must increase strictly; do not shuffle rows")
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError(f"Candle {index}: OHLC values must be finite and positive")
        if values["high"] < max(values.values()) or values["low"] > min(values.values()):
            raise ValueError(f"Candle {index}: inconsistent OHLC range")
        clean.append({"time": timestamp, **values})
        previous_time = timestamp
    return clean


def read_csv(path: Path) -> tuple[list[dict], dict]:
    raw = path.read_bytes()
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"time", "open", "high", "low", "close"}.issubset(reader.fieldnames or ()):
            raise ValueError("CSV requires time,open,high,low,close columns (Unix seconds, bid OHLC)")
        candles = validate_candles(list(reader))
    return candles, {
        "file_name": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(candles),
    }


def closed_features(candles: Sequence[dict], index: int) -> tuple[float, ...]:
    if index < WARMUP - 1 or index >= len(candles):
        raise ValueError(f"Need {WARMUP} completed candles for a feature row")
    bar = candles[index]
    close = bar["close"]
    bar_range = bar["high"] - bar["low"]
    wick_scale = bar_range if bar_range > 0 else 1.0
    returns = [candles[j]["close"] / candles[j - 1]["close"] - 1 for j in range(index - 11, index + 1)]
    true_ranges = [
        max(candles[j]["high"] - candles[j]["low"],
            abs(candles[j]["high"] - candles[j - 1]["close"]),
            abs(candles[j]["low"] - candles[j - 1]["close"]))
        for j in range(index - 13, index + 1)
    ]
    return tuple(
        [close / candles[index - lag]["close"] - 1 for lag in (1, 3, 6, 12)]
        + [(close - bar["open"]) / bar["open"], bar_range / close,
           (bar["high"] - max(bar["open"], close)) / wick_scale,
           (min(bar["open"], close) - bar["low"]) / wick_scale,
           statistics.fmean(true_ranges) / close,
           close / statistics.fmean(b["close"] for b in candles[index - 5:index + 1]) - 1,
           close / statistics.fmean(b["close"] for b in candles[index - 23:index + 1]) - 1,
           statistics.pstdev(returns)]
    )


def build_samples(candles: Sequence[dict], costs: ResearchCosts, horizon: int) -> list[Sample]:
    costs.validate()
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer number of future candles")
    bars = validate_candles(candles)
    samples = []
    for index in range(WARMUP - 1, len(bars) - horizon):
        entry = bars[index + 1]
        exit_bar = bars[index + horizon]
        elapsed_days = (exit_bar["time"] + costs.timeframe_minutes * 60 - entry["time"]) / 86400
        # Input is bid OHLC. Pay spread once at long entry, and adverse slippage
        # on both fills. Per-lot money -> quote-price distance via contract size.
        net_move = (
            exit_bar["close"] - entry["open"]
            - (costs.spread_points + 2 * costs.slippage_points) * costs.point_size
            - costs.commission_round_trip_per_lot / costs.contract_size
            + costs.swap_per_lot_day * elapsed_days / costs.contract_size
        )
        net_return = net_move / entry["open"]
        features = closed_features(bars, index)
        if not math.isfinite(net_return) or not all(math.isfinite(value) for value in features):
            raise ValueError(f"Candle {index}: prices or costs overflowed; check units and source data")
        samples.append(Sample(index, bars[index]["time"] + costs.timeframe_minutes * 60, index + horizon,
                              exit_bar["time"] + costs.timeframe_minutes * 60, features,
                              int(net_return > 0), net_return))
    return samples


def _purge_before(rows: Sequence[Sample], following: Sample) -> list[Sample]:
    return [row for row in rows if row.label_end_index < following.decision_index]


def chronological_partitions(samples: Sequence[Sample]) -> dict[str, list[Sample]]:
    """Fixed 60/20/20; horizon labels cannot enter the following feature period."""
    if len(samples) < 10:
        raise ValueError("Not enough labeled samples for chronological partitions")
    train_end, validation_end = int(len(samples) * .6), int(len(samples) * .8)
    return {
        "train": _purge_before(samples[:train_end], samples[train_end]),
        "validation": _purge_before(samples[train_end:validation_end], samples[validation_end]),
        "test": list(samples[validation_end:]),
    }


def expanding_splits(samples: Sequence[Sample], folds: int = 3) -> list[dict]:
    """Expanding train history, nonoverlapping OOS windows, horizon-purged edges."""
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < 1:
        raise ValueError("folds must be a positive integer")
    if len(samples) < 10:
        raise ValueError("Not enough labeled samples for expanding evaluation")
    first = int(len(samples) * .6)
    width = math.ceil((len(samples) - first) / folds)
    windows = []
    for start in range(first, len(samples), width):
        end = min(len(samples), start + width)
        test = list(samples[start:end])
        if end < len(samples):
            test = _purge_before(test, samples[end])
        windows.append({"train": _purge_before(samples[:start], samples[start]), "test": test})
    return windows


def _summary(samples: Sequence[Sample]) -> dict:
    positive = sum(row.target for row in samples)
    return {
        "samples": len(samples), "positive": positive, "negative": len(samples) - positive,
        "positive_fraction": positive / len(samples) if samples else None,
        "first_decision_time": samples[0].decision_time if samples else None,
        "last_decision_time": samples[-1].decision_time if samples else None,
        "last_label_end_time": samples[-1].label_end_time if samples else None,
        "first_decision_index": samples[0].decision_index if samples else None,
        "last_label_end_index": samples[-1].label_end_index if samples else None,
    }


def probability_metrics(targets: Sequence[int], probabilities: Sequence[float]) -> dict:
    """Brier/log loss and 5 fixed calibration bins, including single-class OOS."""
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

    if not targets:
        raise ValueError("Cannot score an empty held-out window")
    probabilities = [min(1 - 1e-15, max(1e-15, float(value))) for value in probabilities]
    bins = []
    expected_calibration_error = 0.0
    for lower in (0., .2, .4, .6, .8):
        upper = round(lower + .2, 1)
        indices = [i for i, value in enumerate(probabilities) if lower <= value < upper or upper == 1. and value == 1.]
        if not indices:
            bins.append({"lower": lower, "upper": upper, "samples": 0, "mean_probability": None, "observed_fraction": None})
            continue
        prediction = statistics.fmean(probabilities[i] for i in indices)
        observed = statistics.fmean(targets[i] for i in indices)
        expected_calibration_error += len(indices) / len(targets) * abs(prediction - observed)
        bins.append({"lower": lower, "upper": upper, "samples": len(indices), "mean_probability": prediction, "observed_fraction": observed})
    return {
        "samples": len(targets), "brier": float(brier_score_loss(targets, probabilities)),
        "log_loss": float(log_loss(targets, probabilities, labels=[0, 1])),
        "accuracy_at_0_5": float(accuracy_score(targets, [int(value >= .5) for value in probabilities])),
        "single_class_window": len(set(targets)) < 2,
        "expected_calibration_error": expected_calibration_error, "calibration": bins,
    }


def _fit_model(train: Sequence[Sample]):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    model = Pipeline([
        ("scale", StandardScaler()),
        ("logistic", LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=17)),
    ])
    model.fit([row.features for row in train], [row.target for row in train])
    return model


def _score_window(model, train: Sequence[Sample], rows: Sequence[Sample], min_evaluation: int) -> dict:
    result = {"class_balance": _summary(rows)}
    if len(rows) < min_evaluation:
        return {**result, "status": "skipped_insufficient_evaluation_samples"}
    if not train:
        return {**result, "status": "skipped_no_training_samples", "model": None}
    prevalence = statistics.fmean(row.target for row in train)
    majority = int(prevalence >= .5)
    targets = [row.target for row in rows]
    result["baselines"] = {
        "training_prevalence": probability_metrics(targets, [prevalence] * len(rows)),
        "training_majority_class": probability_metrics(targets, [float(majority)] * len(rows)),
    }
    if model is None:
        return {**result, "status": "skipped_single_class_or_insufficient_training", "model": None}
    probabilities = [float(value) for value in model.predict_proba([row.features for row in rows])[:, 1]]
    result.update(status="scored", model=probability_metrics(targets, probabilities))
    result["comparison"] = {
        "brier_improvement_over_training_prevalence": result["baselines"]["training_prevalence"]["brier"] - result["model"]["brier"],
        "log_loss_improvement_over_training_prevalence": result["baselines"]["training_prevalence"]["log_loss"] - result["model"]["log_loss"],
        "automatic_execution_approval": False,
    }
    result["predictions"] = [
        {"decision_time": row.decision_time, "label_end_time": row.label_end_time,
         "decision_index": row.decision_index, "label_end_index": row.label_end_index,
         "probability_net_long_positive": probability, "realized_target": row.target,
         "realized_net_return": row.net_return, "training_prevalence_probability": prevalence}
        for row, probability in zip(rows, probabilities)
    ]
    return result


def run_research(candles: Sequence[dict], costs: ResearchCosts, horizon: int, *,
                 folds: int = 3, min_training: int = 100, min_evaluation: int = 30,
                 dataset_metadata: dict | None = None, model_output: Path | None = None) -> dict:
    """Train once on the first split; validation/test never tune or refit it."""
    for name, value in (("min_training", min_training), ("min_evaluation", min_evaluation)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise ValueError(f"{name} must be an integer >= 2")
    try:
        import sklearn  # noqa: F401 - a clear optional-dependency check
    except ImportError as exc:
        raise RuntimeError("Install optional requirements-ml.txt for offline research") from exc
    bars = validate_candles(candles)
    samples = build_samples(bars, costs, horizon)
    partitions = chronological_partitions(samples)
    train = partitions["train"]

    def fit_if_supported(rows):
        return _fit_model(rows) if len(rows) >= min_training and len({row.target for row in rows}) == 2 else None

    model = fit_if_supported(train)
    dataset = dict(dataset_metadata or {})
    dataset.setdefault("sha256", hashlib.sha256(json.dumps(bars, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    dataset.update(rows=len(bars), first_time=bars[0]["time"], last_time=bars[-1]["time"])
    report = {
        "schema_version": SCHEMA_VERSION, "research_only": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "dataset": dataset,
        "versions": {"python": platform.python_version(), **{name: version(name) for name in ("scikit-learn", "joblib", "numpy", "scipy")}},
        "features": list(FEATURE_NAMES), "warmup_candles": WARMUP,
        "sample_counts": {"labeled": len(samples), "purged_at_chronological_boundaries": len(samples) - sum(len(rows) for rows in partitions.values()),
                          "unlabeled_tail_candles": horizon},
        "label": {"horizon_candles": horizon, "side": "hypothetical_long_only",
                  "definition": "At completed i, enter next bid open plus spread/slippage; exit bid close i+horizon minus slippage. Positive net quote-currency move after commission and signed elapsed-day swap = 1; otherwise 0.",
                  "is_strategy_sl_tp_outcome": False},
        "costs": asdict(costs),
        "method": {"split": "chronological 60/20/20; purge label endpoints >= following split's first feature index",
                   "fit": "StandardScaler + LogisticRegression C=1, seed=17; training rows only; fixed threshold 0.5; no tuning",
                   "walk_forward": "expanding training history, purged boundary horizons, disjoint OOS windows",
                   "minimum_training": min_training, "minimum_evaluation": min_evaluation},
        "training": {"class_balance": _summary(train), "status": "trained" if model is not None else "skipped_single_class_or_insufficient_training"},
        "validation": _score_window(model, train, partitions["validation"], min_evaluation),
        "test": _score_window(model, train, partitions["test"], min_evaluation),
        "walk_forward": [],
        "promotion": {"eligible_for_execution": False, "decision": "manual_research_review_required",
                      "requirements": ["Real broker-data and cost validation", "Fixed-strategy out-of-sample validation", "Independent chronological and walk-forward review", "Extended demo execution/recovery checks", "Separate approval and implementation before any trading integration"]},
        "limitations": [
            "Forecast scores are not a P&L backtest, a calibrated guarantee, or evidence of profitable deployment.",
            "Overlapping within-window horizons create dependent samples; reported metrics have no independence confidence intervals.",
            "Fixed bid spread/slippage, quote-currency commission and continuous signed swap; no broker tick path, SL/TP, margin, conversion, rollover schedule or triple swap simulation.",
            "Input must contain completed candles; the CSV cannot prove that the final candle is closed or that the source history is genuine.",
            "Single-class/undersized training windows are skipped, never counted as successful model validation.",
            "No strategy parameter tuning or automatic model promotion. Trading code does not import this module.",
        ],
    }
    for index, split in enumerate(expanding_splits(samples, folds)):
        fold_model = fit_if_supported(split["train"])
        report["walk_forward"].append({"fold": index + 1, "training": _summary(split["train"]),
                                       "evaluation": _score_window(fold_model, split["train"], split["test"], min_evaluation)})
    if model_output is not None and model is not None:
        import joblib

        model_output = Path(model_output)
        model_output.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": model, "schema_version": SCHEMA_VERSION,
                     "metadata": {key: report[key] for key in ("versions", "dataset", "features", "label", "costs", "method", "training", "promotion")}}, model_output)
        report["artifact"] = {"file_name": model_output.name, "sha256": hashlib.sha256(model_output.read_bytes()).hexdigest(),
                              "warning": "Locally generated research artifact only. Never load untrusted joblib/pickle files; this toolkit exposes no model loader."}
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--horizon", required=True, type=int)
    parser.add_argument("--point-size", required=True, type=float)
    parser.add_argument("--spread-points", required=True, type=float)
    parser.add_argument("--slippage-points", required=True, type=float, help="Adverse points on EACH side")
    parser.add_argument("--commission-round-trip-per-lot", required=True, type=float, help="Nonnegative round trip, in quote currency")
    parser.add_argument("--swap-per-lot-day", required=True, type=float, help="Signed long daily swap in quote currency; negative = cost")
    parser.add_argument("--contract-size", required=True, type=float)
    parser.add_argument("--timeframe-minutes", required=True, type=int)
    parser.add_argument("--quote-currency", required=True)
    parser.add_argument("--symbol", required=True, help="Broker's exact exported symbol")
    parser.add_argument("--folds", default=3, type=int)
    parser.add_argument("--output", type=Path, default=Path("runtime/ml-research.json"))
    parser.add_argument("--model-output", type=Path, help="Optional WRITE-ONLY local joblib artifact; never auto-loaded for trading")
    args = parser.parse_args(argv)
    try:
        candles, dataset = read_csv(args.csv)
        dataset["symbol"] = args.symbol
        costs = ResearchCosts(args.point_size, args.spread_points, args.slippage_points,
                              args.commission_round_trip_per_lot, args.swap_per_lot_day,
                              args.contract_size, args.timeframe_minutes, args.quote_currency)
        if args.output.resolve() == args.csv.resolve() or args.model_output is not None and args.model_output.resolve() in (args.csv.resolve(), args.output.resolve()):
            raise ValueError("Input CSV, report output and model output must use different paths")
        report = run_research(candles, costs, args.horizon, folds=args.folds, dataset_metadata=dataset, model_output=args.model_output)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    except (ValueError, OSError, RuntimeError, UnicodeError) as exc:
        parser.error(str(exc))
    print(f"Saved offline research report: {args.output}. No trading integration or profit claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

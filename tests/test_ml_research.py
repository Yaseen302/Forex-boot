"""Offline fixture checks only: these are not broker-trained profitability evidence."""

import csv
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path

import pytest

pytest.importorskip("sklearn", reason="Optional ML research dependencies not installed")
import numpy as np

from backend import ml_research as ml


@pytest.fixture
def costs():
    return ml.ResearchCosts(point_size=.00001, spread_points=10, slippage_points=1,
                            commission_round_trip_per_lot=7, swap_per_lot_day=-3,
                            contract_size=100000, timeframe_minutes=30, quote_currency="USD")


def fixture_bars(count=600, *, rising_only=False):
    bars = []
    for i in range(count):
        opening = 1.1 + i * .000001 + (0 if rising_only else .003 * math.sin(i / 7))
        close = opening + (.0004 if rising_only else .00045 * math.sin(i / 4))
        bars.append({"time": 1700000000 + i * 1800, "open": opening,
                     "close": close, "high": max(opening, close) + .0002,
                     "low": min(opening, close) - .0002})
    return bars


def test_future_prices_cannot_change_existing_features(costs):
    original = fixture_bars(100)
    modified = [dict(row) for row in original]
    for row in modified[51:]:
        for key in ("open", "high", "low", "close"):
            row[key] *= 1.5
    before = next(row for row in ml.build_samples(original, costs, 4) if row.decision_index == 50)
    after = next(row for row in ml.build_samples(modified, costs, 4) if row.decision_index == 50)
    assert before.features == after.features
    assert before.net_return != after.net_return
    assert len(before.features) == len(ml.FEATURE_NAMES)


def test_label_uses_next_open_and_full_explicit_costs(costs):
    bars = fixture_bars(60)
    i, horizon = 30, 3
    sample = next(row for row in ml.build_samples(bars, costs, horizon) if row.decision_index == i)
    days = 3 * 1800 / 86400
    expected = (bars[i + horizon]["close"] - bars[i + 1]["open"]
                - .00001 * (10 + 2)
                - 7 / 100000 - 3 * days / 100000) / bars[i + 1]["open"]
    assert sample.net_return == pytest.approx(expected)
    assert sample.target == int(expected > 0)
    assert sample.decision_time == bars[i]["time"] + 1800
    assert sample.label_end_time == bars[i + horizon]["time"] + 1800
    assert sample.label_end_index == sample.decision_index + horizon


def test_chronological_boundaries_purge_every_future_horizon(costs):
    samples = ml.build_samples(fixture_bars(), costs, 5)
    split = ml.chronological_partitions(samples)
    assert split["train"][-1].label_end_index < split["validation"][0].decision_index
    assert split["validation"][-1].label_end_index < split["test"][0].decision_index
    assert len(samples) - sum(len(rows) for rows in split.values()) == 10
    assert set(row.decision_index for row in split["train"]).isdisjoint(row.decision_index for row in split["test"])


def test_expanding_folds_purge_labels_and_disjoin_test_windows(costs):
    splits = ml.expanding_splits(ml.build_samples(fixture_bars(), costs, 4), 3)
    seen_test = set()
    previous_train_size = 0
    for split in splits:
        train, test = split["train"], split["test"]
        assert train[-1].label_end_index < test[0].decision_index
        test_indices = {row.decision_index for row in test}
        assert seen_test.isdisjoint(test_indices)
        assert len(train) > previous_train_size
        seen_test.update(test_indices)
        previous_train_size = len(train)
    for first, following in zip(splits, splits[1:]):
        assert first["test"][-1].label_end_index < following["test"][0].decision_index


def test_scaler_fit_has_training_mean_only(costs):
    samples = ml.build_samples(fixture_bars(), costs, 3)
    split = ml.chronological_partitions(samples)
    model = ml._fit_model(split["train"])
    expected = np.mean([row.features for row in split["train"]], axis=0)
    all_data_mean = np.mean([row.features for row in samples], axis=0)
    np.testing.assert_allclose(model.named_steps["scale"].mean_, expected)
    assert not np.allclose(expected, all_data_mean, atol=1e-10)
    assert model.named_steps["scale"].n_samples_seen_ == len(split["train"])


def test_report_has_held_out_metrics_baselines_and_no_promotion(costs):
    report = ml.run_research(fixture_bars(), costs, 3)
    assert report["training"]["status"] == "trained"
    assert report["research_only"] is True
    for name in ("validation", "test"):
        split = report[name]
        assert split["status"] == "scored"
        assert set(split["baselines"]) == {"training_prevalence", "training_majority_class"}
        assert sum(bin_["samples"] for bin_ in split["model"]["calibration"]) == split["model"]["samples"]
        assert split["class_balance"]["positive"] > 0
        assert split["class_balance"]["negative"] > 0
        assert 0 <= split["model"]["brier"] <= 1
        assert split["comparison"]["automatic_execution_approval"] is False
        assert len(split["predictions"]) == split["model"]["samples"]
    assert report["promotion"]["eligible_for_execution"] is False
    json.dumps(report, allow_nan=False)


def test_predictions_are_deterministic_without_heldout_refit(costs):
    bars = fixture_bars()
    first = ml.run_research(bars, costs, 3)
    second = ml.run_research(bars, costs, 3)
    assert first["test"]["predictions"] == second["test"]["predictions"]
    assert first["dataset"]["sha256"] == second["dataset"]["sha256"]


def test_changing_heldout_prices_cannot_change_fitted_training_pipeline(costs, monkeypatch):
    bars = fixture_bars()
    samples = ml.build_samples(bars, costs, 3)
    first_test_index = ml.chronological_partitions(samples)["test"][0].decision_index
    fitted = []
    original_fit = ml._fit_model

    def capture_train(rows):
        model = original_fit(rows)
        fitted.append(model)
        return model

    monkeypatch.setattr(ml, "_fit_model", capture_train)
    ml.run_research(bars, costs, 3)
    first_model = fitted[0]
    fitted.clear()
    altered = [dict(row) for row in bars]
    for row in altered[first_test_index:]:
        for key in ("open", "high", "low", "close"):
            row[key] *= 1.5
    ml.run_research(altered, costs, 3)
    np.testing.assert_array_equal(first_model.named_steps["scale"].mean_, fitted[0].named_steps["scale"].mean_)
    np.testing.assert_array_equal(first_model.named_steps["logistic"].coef_, fitted[0].named_steps["logistic"].coef_)


def test_single_class_training_skips_and_writes_no_model(costs, tmp_path):
    zero_cost = replace(costs, spread_points=0, slippage_points=0,
                        commission_round_trip_per_lot=0, swap_per_lot_day=0)
    output = tmp_path / "never-trained.joblib"
    report = ml.run_research(fixture_bars(rising_only=True), zero_cost, 3, model_output=output)
    assert report["training"]["status"] == "skipped_single_class_or_insufficient_training"
    assert report["test"]["status"] == "skipped_single_class_or_insufficient_training"
    assert report["test"]["model"] is None
    assert report["test"]["baselines"]["training_prevalence"]["single_class_window"] is True
    assert not output.exists()
    assert "artifact" not in report
    assert report["promotion"]["eligible_for_execution"] is False


def test_insufficient_purged_training_never_trains(costs):
    report = ml.run_research(fixture_bars(100), costs, 40, min_training=2, min_evaluation=2)
    assert report["training"]["class_balance"]["samples"] == 0
    assert report["test"]["status"] == "skipped_no_training_samples"


@pytest.mark.parametrize("mutation,message", [
    (lambda bars: bars[1].update(time=bars[0]["time"]), "increase strictly"),
    (lambda bars: bars[1].update(close=float("nan")), "finite and positive"),
    (lambda bars: bars[1].update(high=.5), "inconsistent OHLC"),
    (lambda bars: bars[1].pop("open"), "expected numeric"),
])
def test_bad_data_rejected(mutation, message):
    bars = fixture_bars(50)
    mutation(bars)
    with pytest.raises(ValueError, match=message):
        ml.validate_candles(bars)


def test_invalid_costs_and_horizon_rejected(costs):
    for bad in (replace(costs, spread_points=-1), replace(costs, contract_size=0),
                replace(costs, point_size=float("inf")), replace(costs, timeframe_minutes=0)):
        with pytest.raises(ValueError):
            ml.build_samples(fixture_bars(50), bad, 3)
    with pytest.raises(ValueError, match="horizon"):
        ml.build_samples(fixture_bars(50), costs, 0)


def test_csv_cli_outputs_dataset_and_artifact_hash_without_loader(tmp_path):
    source = tmp_path / "fixture-not-broker.csv"
    rows = fixture_bars()
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time", "open", "high", "low", "close"])
        writer.writeheader()
        writer.writerows(rows)
    report_path, model_path = tmp_path / "research.json", tmp_path / "local.joblib"
    assert ml.main([str(source), "--horizon", "3", "--point-size", ".00001",
                    "--spread-points", "10", "--slippage-points", "1",
                    "--commission-round-trip-per-lot", "7", "--swap-per-lot-day", "-3",
                    "--contract-size", "100000", "--timeframe-minutes", "30",
                    "--quote-currency", "USD", "--symbol", "FIXTURE_ONLY",
                    "--output", str(report_path), "--model-output", str(model_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report["dataset"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["dataset"]["symbol"] == "FIXTURE_ONLY"
    assert report["artifact"]["sha256"] == hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert "joblib.load" not in Path(ml.__file__).read_text()


def test_csv_columns_are_required(tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("time,close\n1,1.1\n")
    with pytest.raises(ValueError, match="requires time,open,high,low,close"):
        ml.read_csv(source)

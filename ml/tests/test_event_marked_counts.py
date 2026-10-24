"""Synthetic contract tests for the marked-count event generator (research only)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from tests.event_forecaster_fixtures import history, histories
from zavozik_ml import calendar as cal
from zavozik_ml.event_forecasters.core import EVENT_COLUMNS, EventHistory, FitOptions
from zavozik_ml.event_forecasters.marked_counts import Model

FAST = dict(rounds=15, threads=1)


def fit(model_histories, **options):
    return Model(FitOptions(**(FAST | options))).fit(model_histories)


def records(days=120, events=(), company="synthetic", industry="synthetic_industry"):
    dates = np.arange(np.datetime64("2025-01-01"),
                      np.datetime64("2025-01-01") + np.timedelta64(days, "D"))
    frame = pd.DataFrame(list(events),
                         columns=["date", "direction", "amount", "category", "counterparty"])
    return EventHistory(company, industry, dates, np.zeros(days, dtype=bool),
                        np.full(days, np.datetime64("NaT", "D")), frame)


def flat_history(days=200, amount=0.0, company="flat"):
    """Two one-mark streams every working day, with a constant amount."""
    dates = np.arange(np.datetime64("2025-01-01"),
                      np.datetime64("2025-01-01") + np.timedelta64(days, "D"))
    rows = []
    for day in dates:
        if not cal.is_workday([day])[0]:
            continue
        for direction, mark in ((0, "flow"), (1, "cost")):
            for _ in range(2):
                rows.append(dict(date=pd.Timestamp(day), direction=direction, amount=amount,
                                 category=mark, counterparty=""))
    return records(days=days, events=rows, company=company)


def coupled_history(days=280, high=1000.0, low=20.0, company="coupled"):
    """Amount level switches every 20 days for both directions together."""
    dates = np.arange(np.datetime64("2025-01-01"),
                      np.datetime64("2025-01-01") + np.timedelta64(days, "D"))
    rows = []
    for index, day in enumerate(dates):
        if not cal.is_workday([day])[0]:
            continue
        level = high if (index // 20) % 2 == 0 else low
        for direction, mark, scale in ((0, "flow", 1.0), (1, "cost", 0.5)):
            for _ in range(2):
                rows.append(dict(date=pd.Timestamp(day), direction=direction,
                                 amount=level * scale, category=mark, counterparty=""))
    return records(days=days, events=rows, company=company)


def inflow_only_history(days=200, company="inflow-only"):
    dates = np.arange(np.datetime64("2025-01-01"),
                      np.datetime64("2025-01-01") + np.timedelta64(days, "D"))
    rows = [dict(date=pd.Timestamp(day), direction=0, amount=float(100 + i % 7), category="sales",
                 counterparty="")
            for i, day in enumerate(dates) if cal.is_workday([day])[0]]
    return records(days=days, events=rows, company=company)


def censored_pair(source, window, discovered_on=None):
    """Same observation masks, but one view still holds the undiscovered rows."""
    missing, detected = source.missing.copy(), source.detected.copy()
    missing[window] = True
    detected[window] = source.dates[-1] if discovered_on is None else np.datetime64(discovered_on, "D")
    leaked = EventHistory(source.company_id, source.industry, source.dates.copy(), missing,
                          detected, source.raw_events.copy())
    keep = ~leaked.raw_events.date.isin(pd.to_datetime(source.dates[window]))
    clean = EventHistory(source.company_id, source.industry, source.dates.copy(), missing,
                         detected, leaked.raw_events[keep].copy())
    return leaked, clean


def test_generated_paths_validate_and_reconcile():
    hs = histories(3)
    model = fit(hs)
    paths = model.sample(hs[0], 30, 40, np.random.default_rng(11))
    events = paths.events
    assert list(events.columns) == EVENT_COLUMNS
    assert paths.validate() is paths
    json.dumps(paths.diagnostics)  # diagnostics stay reportable
    assert events.direction.isin([0, 1]).all()
    assert events.path.between(0, 39).all() and events.day.between(1, 30).all()
    assert np.isfinite(events.amount).all() and (events.amount >= 0).all()
    assert (events.category.astype(str).str.len() > 0).all()
    assert (events.counterparty == "").all() and (events.known_event_id == "").all()

    amounts, counts = paths.daily()
    assert amounts.shape == counts.shape == (40, 30, 2)
    # Every individual event is retained, and daily totals reconcile exactly.
    assert counts.sum() == len(events)
    np.testing.assert_allclose(amounts.sum(), events.amount.sum())
    expected_amounts = np.zeros_like(amounts)
    expected_counts = np.zeros_like(counts)
    np.add.at(expected_amounts, (events.path.to_numpy(int), events.day.to_numpy(int) - 1,
                                events.direction.to_numpy(int)), events.amount.to_numpy(float))
    np.add.at(expected_counts, (events.path.to_numpy(int), events.day.to_numpy(int) - 1,
                                events.direction.to_numpy(int)), 1.0)
    np.testing.assert_allclose(expected_amounts, amounts)
    np.testing.assert_allclose(expected_counts, counts)


def test_sampling_is_deterministic_for_one_seed():
    hs = histories(3)
    model = fit(hs)
    first = model.sample(hs[0], 20, 25, np.random.default_rng(5))
    again = model.sample(hs[0], 20, 25, np.random.default_rng(5))
    other = model.sample(hs[0], 20, 25, np.random.default_rng(6))
    assert first.events.equals(again.events)
    assert first.diagnostics == again.diagnostics
    assert not first.events.amount.equals(other.events.amount)


def test_zero_event_evidence_yields_valid_empty_paths():
    empty = records(days=120)
    model = fit([empty])
    paths = model.sample(empty, 15, 6, np.random.default_rng(0))
    amounts, counts = paths.daily()
    assert len(paths.events) == 0
    assert not amounts.any() and not counts.any()
    assert counts.shape == (6, 15, 2)
    assert paths.diagnostics["events"] == 0
    assert paths.diagnostics["training_rows"] > 0  # observed silence is evidence, not missing data
    assert model.sample(empty, 15, 6, np.random.default_rng(0)).events.empty


def test_missing_days_are_not_zero_observations():
    source = history(days=240)
    censored, _ = censored_pair(source, slice(100, 110))
    assert not censored.known[100:110].any()
    with_gap = fit([censored])
    without_gap = fit([source])

    # Ten censored days leave the training set and are not read as observed zeros;
    # the 28 days after the gap lose their exposure window and drop out as well.
    assert with_gap.fit_diagnostics_["training_rows"] == 240 - 28 - 10 - 28
    assert without_gap.fit_diagnostics_["training_rows"] == 240 - 28
    assert with_gap.fit_diagnostics_["observed_events"]["out"] \
        < without_gap.fit_diagnostics_["observed_events"]["out"]
    # The same cells are complete history while the exporter has not discovered the gap.
    undiscovered, _ = censored_pair(source, slice(100, 110),
                                    discovered_on=source.dates[-1] + np.timedelta64(1, "D"))
    assert undiscovered.known[100:110].all()
    assert undiscovered.events.equals(source.events)
    assert fit([undiscovered]).fit_diagnostics_["training_rows"] == 240 - 28


def test_censored_raw_events_cannot_leak_into_fit_or_sample():
    source = history(days=240)
    leaked, clean = censored_pair(source, slice(200, 235))
    assert leaked.events.equals(clean.events)
    model_a = fit([leaked])
    model_b = fit([clean])
    assert model_a.fit_diagnostics_ == model_b.fit_diagnostics_
    first = model_a.sample(leaked, 20, 30, np.random.default_rng(9))
    second = model_b.sample(clean, 20, 30, np.random.default_rng(9))
    assert first.events.equals(second.events)


def test_nonworking_days_are_excluded_when_calendar_only():
    hs = histories(3)
    model = fit(hs)
    paths = model.sample(hs[1], 30, 30, np.random.default_rng(2))
    dated = paths.dated_events()
    assert len(dated) > 0
    assert cal.is_workday(dated.date.to_numpy()).all()
    assert paths.diagnostics["disallowed_days"] > 0


def test_same_day_events_and_zero_amounts_are_kept():
    source = flat_history(amount=0.0)
    model = fit([source])
    paths = model.sample(source, 20, 30, np.random.default_rng(3))
    events = paths.events
    assert len(events) > 0
    assert (events.amount == 0.0).all()  # zero amounts survive, they are not dropped rows
    _, counts = paths.daily()
    assert paths.diagnostics["zero_amount_events"] == len(events)
    assert counts.max() >= 2  # several same-day events in one scenario are ordinary


def test_category_smoothing_keeps_pool_and_recurring_marks():
    hs = histories(3)
    model = fit(hs)
    paths = model.sample(hs[0], 30, 100, np.random.default_rng(4))
    events = paths.events
    shares = events.category.value_counts(normalize=True)
    assert shares.get("sales", 0.0) > 0.4  # dominant pooled mark
    assert 0 < shares.get("rent", 0.0) < 0.25  # rare recurring mark stays reachable
    amounts = events.groupby("category").amount.mean()
    assert amounts["rent"] > 2 * amounts["purchase"]  # amounts follow the mark


def test_company_amount_scale_is_conditioned():
    small = flat_history(amount=10.0, company="small")
    large = flat_history(amount=1000.0, company="large")
    model = fit([small, large])
    small_paths = model.sample(small, 20, 20, np.random.default_rng(7))
    large_paths = model.sample(large, 20, 20, np.random.default_rng(7))
    assert len(small_paths.events) and len(large_paths.events)
    assert large_paths.events.amount.mean() > 20 * small_paths.events.amount.mean()


def test_sparse_direction_evidence_is_not_fabricated():
    source = inflow_only_history()
    model = fit([source])
    paths = model.sample(source, 20, 20, np.random.default_rng(8))
    events = paths.events
    assert len(events) > 0
    assert set(events.direction) == {0}
    assert (events.category.astype(str).str.len() > 0).all()
    # An unseen company can still be sampled from the pooled marks and pools.
    unseen = inflow_only_history(days=20, company="unseen")
    pooled = model.sample(unseen, 10, 5, np.random.default_rng(8))
    assert pooled.validate() is pooled


def test_shared_activity_block_couples_direction_amounts():
    source = coupled_history()
    model = fit([source])
    paths = model.sample(source, 20, 120, np.random.default_rng(13))
    assert paths.diagnostics["activity_regime"] == "historical_blocks"
    assert paths.diagnostics["regime_blocks"] > 0
    amounts, _ = paths.daily()
    inflow, outflow = amounts[:, :, 0].sum(axis=1), amounts[:, :, 1].sum(axis=1)
    correlation = float(np.corrcoef(inflow, outflow)[0, 1])
    # Independent per-event amount draws would decorrelate the two directions.
    assert correlation > 0.5


def test_dispersion_is_estimated_or_documented_fallback():
    hs = histories(3)
    model = fit(hs)
    for direction in ("in", "out"):
        shape = model.fit_diagnostics_["dispersion"][direction]
        assert 1.0 <= shape <= 200.0
        assert model.fit_diagnostics_["dispersion_method"][direction] in {
            "heldout_method_of_moments", "underdispersed_upper_bound", "geometric_fallback"}
    thin = fit([history(days=60, seed=2)])
    assert thin.fit_diagnostics_["dispersion"] == {"in": 1.0, "out": 1.0}
    assert set(thin.fit_diagnostics_["dispersion_method"].values()) == {"geometric_fallback"}


def test_unfitted_pool_falls_back_to_visible_daily_rates():
    source = history(days=200, seed=4)
    model = fit([])  # no fit evidence at all: pooled visible rates decide
    paths = model.sample(source, 20, 400, np.random.default_rng(1))
    _, counts = paths.daily()
    simulated = counts[:, :, 0].sum() / (paths.diagnostics["allowed_days"] * 400)
    visible = source.daily_counts[source.known & source.allowed(source.dates), 0].mean()
    assert 0.75 * visible < simulated < 1.35 * visible


def test_count_cap_reports_clipping_instead_of_fabricating():
    hs = histories(3)
    model = fit(hs, max_events_per_day=2)
    paths = model.sample(hs[0], 30, 40, np.random.default_rng(12))
    _, counts = paths.daily()
    assert counts.sum(axis=2).max() <= 2
    assert paths.diagnostics["clipping"]["count_cap_rows"] > 0
    assert paths.diagnostics["clipping"]["count_cap_events"] > 0


def test_options_are_validated_and_history_is_not_mutated():
    hs = histories(2)
    before = [h.events.copy() for h in hs]
    model = fit(hs)
    with pytest.raises(ValueError):
        model.sample(hs[0], 0, 5, np.random.default_rng(0))
    with pytest.raises(ValueError):
        model.sample(hs[0], 5, 0, np.random.default_rng(0))
    model.sample(hs[0], 5, 5, np.random.default_rng(0))
    for old, new in zip(before, hs):
        assert old.equals(new.events)

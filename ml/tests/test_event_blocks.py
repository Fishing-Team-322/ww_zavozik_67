"""Behavioural tests for the whole-event block resampling forecaster.

All fixtures are tiny synthetic histories; none of them is evaluation data.
"""
import numpy as np
import pandas as pd
import pytest

from tests.event_forecaster_fixtures import histories
from zavozik_ml import calendar as cal
from zavozik_ml.event_forecasters import blocks
from zavozik_ml.event_forecasters.blocks import Model
from zavozik_ml.event_forecasters.core import EventHistory, FitOptions

COLUMNS = ["date", "direction", "amount", "category", "counterparty"]
START = np.datetime64("1970-01-01", "D")


def _span(start, days):
    first = np.datetime64(start, "D")
    return first + np.arange(days).astype("timedelta64[D]")


def _workdays(start, days):
    dates = _span(start, days)
    return list(dates[cal.is_workday(dates)])


def _history(start, days, records, company_id="blocks-company", industry="blocks-industry", missing=None):
    dates = _span(start, days)
    missing = np.zeros(days, dtype=bool) if missing is None else np.asarray(missing, dtype=bool)
    detected = np.full(days, np.datetime64("NaT", "D"))
    detected[missing] = dates[-1]
    frame = pd.DataFrame(records, columns=COLUMNS)
    return EventHistory(company_id, industry, dates, missing, detected, frame)


def _target(history, horizon):
    return history.dates[-1] + np.arange(1, horizon + 1).astype("timedelta64[D]")


def _constant_history(amount_in=100.0, amount_out=40.0):
    rows = []
    for day in _workdays("2024-01-01", 200):
        stamp = pd.Timestamp(day)
        rows.append(dict(date=stamp, direction=0, amount=amount_in, category="sales", counterparty="shop"))
        rows.append(dict(date=stamp, direction=1, amount=amount_out, category="buy", counterparty="shop"))
    return _history("2024-01-01", 200, rows)


def _drift_history(start="2023-01-01", days=500):
    dates = _span(start, days)
    rows = []
    for day in _workdays(start, days):
        offset = int((day - dates[0]).astype(int))
        amount = 100.0 if offset < days - blocks._LEVEL_RECENT_DAYS else 500.0
        rows.append(dict(date=pd.Timestamp(day), direction=0, amount=amount, category="sales",
                         counterparty="shop"))
    return _history(start, days, rows)


def _varied_history(start="2024-01-01", days=260, seed=21):
    generator = np.random.default_rng(seed)
    rows = []
    for day in _workdays(start, days):
        stamp = pd.Timestamp(day)
        for _ in range(int(generator.integers(1, 4))):
            rows.append(dict(date=stamp, direction=0, amount=float(generator.gamma(3.0, 50.0)),
                             category="sales", counterparty="shop"))
        if generator.random() < 0.6:
            rows.append(dict(date=stamp, direction=1, amount=float(generator.gamma(2.0, 40.0)),
                             category="buy", counterparty="supplier"))
    return _history(start, days, rows)


def _monthly_history(start="2024-01-01", days=366, amount=900.0):
    """One payment on the 5th that falls on a workday, for twelve months."""
    rows = []
    for month in pd.date_range(start, periods=12, freq="MS"):
        day = month + pd.Timedelta(days=4)
        if cal.is_workday([np.datetime64(day.date(), "D")])[0]:
            rows.append(dict(date=day, direction=1, amount=amount, category="rent",
                             counterparty="landlord"))
    return _history(start, days, rows)


def test_sample_is_deterministic_and_reconciles_with_daily_totals():
    window = histories(3, days=200)
    target = window[0].prefix(window[0].dates[150])
    first = Model(FitOptions(seed=11)).fit(window).sample(target, 30, 20, np.random.default_rng(4))
    second = Model(FitOptions(seed=11)).fit(window).sample(target, 30, 20, np.random.default_rng(4))
    pd.testing.assert_frame_equal(first.events, second.events)

    amounts, counts = first.daily()
    assert amounts.shape == counts.shape == (20, 30, 2)
    assert np.isfinite(amounts).all() and (amounts >= 0).all()
    assert first.events.direction.isin([0, 1]).all()
    assert (first.events.known_event_id.astype(str) == "").all()
    assert first.events.category.astype(str).str.len().gt(0).all()

    manual_amounts = np.zeros_like(amounts)
    manual_counts = np.zeros_like(counts)
    index = (first.events.path.to_numpy(int), first.events.day.to_numpy(int) - 1,
             first.events.direction.to_numpy(int))
    np.add.at(manual_amounts, index, first.events.amount.to_numpy(float))
    np.add.at(manual_counts, index, 1.0)
    np.testing.assert_allclose(manual_amounts, amounts)
    np.testing.assert_allclose(manual_counts, counts)
    assert first.diagnostics["donor_mode"] == "day"


def test_donor_days_keep_every_event_including_zero_amounts():
    rows = []
    for day in _workdays("2025-01-01", 70):
        stamp = pd.Timestamp(day)
        rows += [
            dict(date=stamp, direction=0, amount=100.0, category="sales", counterparty="shop"),
            dict(date=stamp, direction=0, amount=0.0, category="sales", counterparty="shop"),
            dict(date=stamp, direction=1, amount=55.5, category="purchase", counterparty="shop"),
        ]
    history = _history("2025-01-01", 70, rows)
    paths = Model().fit([history]).sample(history, 28, 15, np.random.default_rng(2))
    amounts, counts = paths.daily()
    allowed = history.allowed(_target(history, 28))

    np.testing.assert_allclose(counts[:, allowed, 0], 2.0)
    np.testing.assert_allclose(counts[:, allowed, 1], 1.0)
    np.testing.assert_allclose(amounts[:, allowed, 0], 100.0)
    np.testing.assert_allclose(amounts[:, allowed, 1], 55.5)
    zero = paths.events[paths.events.amount == 0]
    assert len(zero) == int(allowed.sum()) * 15
    # Company-local donor identities are real for this company and are kept.
    assert set(paths.events.counterparty.astype(str)) == {"shop"}


def test_empty_streams_emit_zero_events_without_resampling_loops():
    empty = _history("2025-03-01", 40, [])
    paths = Model().fit([]).sample(empty, 30, 6, np.random.default_rng(0))
    allowed = int(empty.allowed(_target(empty, 30)).sum())
    amounts, counts = paths.daily()
    assert len(paths.events) == 0
    assert amounts.shape == counts.shape == (6, 30, 2)
    assert not amounts.any() and not counts.any()
    assert paths.diagnostics["donor_source_counts"]["none"] == allowed * 6
    assert paths.diagnostics["masked_days"] == 30 - allowed


def test_industry_donors_back_off_for_empty_local_streams():
    rows = [dict(date=pd.Timestamp(day), direction=0, amount=400.0, category="sales",
                 counterparty="foreign-bank")
            for day in _workdays("2025-01-01", 120)]
    donor = _history("2025-01-01", 120, rows, company_id="donor", industry="shared")
    silent = _history("2025-01-01", 120, [], company_id="silent", industry="shared")
    model = Model().fit([donor.prefix(donor.dates[100])])
    paths = model.sample(silent.prefix(silent.dates[100]), 20, 12, np.random.default_rng(3))

    assert paths.diagnostics["donor_source_counts"]["local"] == 0
    assert paths.diagnostics["donor_source_counts"]["industry"] > 0
    assert len(paths.events) > 0
    assert set(paths.events.category.astype(str)) == {"sales"}
    # Another company's counterparty identity is never transferred.
    assert (paths.events.counterparty.astype(str) == "").all()
    assert (paths.events.known_event_id.astype(str) == "").all()
    # Donor amounts are company-relative; the silent company's unit scale shows that.
    np.testing.assert_allclose(paths.events.amount.to_numpy(float), 1.0)


def test_day_blocks_follow_the_target_weekday():
    rows = []
    for day in _workdays("2025-01-01", 84):
        stamp = pd.Timestamp(day)
        if stamp.dayofweek == 0:
            rows += [dict(date=stamp, direction=0, amount=10.0, category="monday", counterparty="")] * 2
        elif stamp.dayofweek == 2:
            rows.append(dict(date=stamp, direction=1, amount=7.0, category="wednesday", counterparty=""))
    history = _history("2025-01-01", 84, rows)
    paths = Model().fit([history]).sample(history, 35, 8, np.random.default_rng(6))
    _, counts = paths.daily()
    target = _target(history, 35)
    weekday = pd.DatetimeIndex(target).dayofweek.to_numpy()
    allowed = history.allowed(target)
    total = counts.sum(axis=2)

    assert (total[:, allowed & (weekday == 0)] == 2).all()
    assert (total[:, allowed & (weekday == 2)] == 1).all()
    assert (total[:, allowed & ~np.isin(weekday, [0, 2])] == 0).all()


def test_week_blocks_reproduce_weekly_dependence():
    generator = np.random.default_rng(0)
    rows = []
    for week_start in pd.date_range("2025-01-06", periods=13, freq="7D"):
        if generator.random() < 0.5:
            continue  # idle week: no events at all, donor week must stay whole
        for offset in range(5):
            stamp = week_start + pd.Timedelta(days=offset)
            if not cal.is_workday([np.datetime64(stamp.date(), "D")])[0]:
                continue
            for _ in range(3):
                rows.append(dict(date=stamp, direction=0, amount=25.0, category="sales", counterparty=""))
    history = _history("2025-01-06", 91, rows)
    model = Model().fit([history])
    paths = model.sample(history, 28, 24, np.random.default_rng(9))

    assert paths.diagnostics["donor_mode"] == "week"
    assert paths.diagnostics["weekly_dependence"] > 0.2
    _, counts = paths.daily()
    target = _target(history, 28)
    allowed = history.allowed(target)
    weeks = pd.DatetimeIndex(target).isocalendar().week.to_numpy()
    total = counts.sum(axis=2)
    observed = 0
    for week in np.unique(weeks):
        days = np.flatnonzero((weeks == week) & allowed)
        if len(days) < 2:
            continue
        block = total[:, days]
        busy = (block == 3).all(axis=1)
        idle = (block == 0).all(axis=1)
        assert (busy | idle).all(), "a week block must stay busy or idle as a whole"
        observed += int(busy.sum() + idle.sum())
    assert observed and (total == 3).any() and (total == 0).any()


def test_unknown_days_and_their_weeks_are_not_donors():
    start, days = "2025-01-01", 120
    dates = _span(start, days)
    missing = np.ones(days, dtype=bool)
    closed = np.zeros(days, dtype=bool)
    closed[12:19] = True   # 2025-01-13..19 fully observed
    closed[20:24] = True   # 2025-01-21..24 observed, 2025-01-20 stays unknown
    missing[closed] = False
    rows = []
    for day in _workdays(start, days):
        offset = int((day - dates[0]).astype(int))
        mark = ("hidden_week" if missing[offset] else
                "known_week" if offset < 19 else "partial_week")
        rows.append(dict(date=pd.Timestamp(day), direction=0, amount=90.0, category=mark,
                         counterparty=""))
    history = _history(start, days, rows, missing=missing)
    assert set(history.events.category.astype(str)) == {"known_week", "partial_week"}

    model = Model().fit([history])
    assert model.fit_diagnostics["global_donor_days"] == 9
    # The week with an unknown Monday is rejected as a week block, never read as
    # four observed quiet days plus an assumed Monday.
    assert model.fit_diagnostics["global_donor_weeks"] == 1
    assert model.fit_diagnostics["global_weeks_rejected_unknown"] == 1

    paths = model.sample(history, 20, 6, np.random.default_rng(1))
    assert len(paths.events) > 0
    assert "hidden_week" not in set(paths.events.category.astype(str))


def test_fully_unknown_history_has_no_donors():
    missing = np.zeros(120, dtype=bool)
    rows = []
    for day in _workdays("2025-01-01", 120):
        rows.append(dict(date=pd.Timestamp(day), direction=0, amount=90.0, category="sales",
                         counterparty=""))
        missing[int((day - np.datetime64("2025-01-01", "D")).astype(int))] = True
    history = _history("2025-01-01", 120, rows, missing=missing)
    # Every event-bearing day is unknown at this cutoff; calendar closed days
    # stay known but empty.
    assert not (history.known & cal.is_workday(history.dates)).any()
    assert len(history.events) == 0

    model = Model().fit([history])
    assert model.fit_diagnostics["global_donor_days"] == 0
    assert model.fit_diagnostics["global_donor_weeks"] == 0

    allowed = int(history.allowed(_target(history, 20)).sum())
    paths = model.sample(history, 20, 5, np.random.default_rng(1))
    assert len(paths.events) == 0
    assert paths.diagnostics["local_backoff"] == "empty"
    assert paths.diagnostics["donor_source_counts"]["none"] == allowed * 5


def test_event_cap_clips_and_is_reported():
    rows = []
    for day in _workdays("2025-02-03", 42):
        for _ in range(9):
            rows.append(dict(date=pd.Timestamp(day), direction=0, amount=5.0, category="sales",
                             counterparty=""))
    history = _history("2025-02-03", 42, rows)
    paths = Model(FitOptions(max_events_per_day=4)).fit([history]).sample(
        history, 12, 6, np.random.default_rng(8))
    _, counts = paths.daily()
    assert counts.sum(axis=2).max() == 4
    assert paths.diagnostics["cap_events_per_day"] == 4
    assert paths.diagnostics["clipped_events"] > 0


def test_target_allowed_mask_keeps_nonworking_days_empty():
    window = histories(2, days=180)
    history = window[0]
    paths = Model().fit(window).sample(history, 60, 10, np.random.default_rng(5))
    target = _target(history, 60)
    nonworking = target[~history.allowed(target)]
    dated = paths.dated_events().date.to_numpy(dtype="datetime64[D]")
    assert len(nonworking) and not np.isin(dated, nonworking).any()
    assert paths.diagnostics["masked_days"] == len(nonworking)
    assert paths.diagnostics["allowed_days"] == int(history.allowed(target).sum())
    assert paths.diagnostics["calendar_filtered"] is True


def test_fit_pools_never_leak_events_after_the_sampling_cutoff():
    start, days = "2025-01-01", 260
    rows = []
    for day in _workdays(start, days):
        stamp = pd.Timestamp(day)
        mark = "past_mark" if stamp < pd.Timestamp("2025-05-01") else "future_mark"
        rows.append(dict(date=stamp, direction=0, amount=30.0, category=mark, counterparty=""))
    donor = _history(start, days, rows, company_id="donor", industry="ind")
    silent = _history(start, days, [], company_id="silent", industry="ind")
    model = Model().fit([donor, silent])

    early = model.sample(silent.prefix(silent.dates[104]), 20, 8, np.random.default_rng(7))
    assert len(early.events) > 0
    assert set(early.events.category.astype(str)) == {"past_mark"}

    late = model.sample(silent, 20, 8, np.random.default_rng(7))
    assert "future_mark" in set(late.events.category.astype(str))


def test_single_day_horizon_and_single_path():
    history = histories(1, days=120)[0]
    paths = Model().fit([history]).sample(history, 1, 1, np.random.default_rng(0))
    amounts, counts = paths.daily()
    assert amounts.shape == (1, 1, 2)
    assert len(paths.events) == int(counts.sum())
    with pytest.raises(ValueError):
        Model().sample(history, 0, 1, np.random.default_rng(0))


def test_week_mode_falls_back_when_no_donor_week_covers_the_target():
    generator = np.random.default_rng(3)
    rows = []
    missing = np.zeros(91, dtype=bool)
    for week_start in pd.date_range("2025-01-06", periods=13, freq="7D"):
        for offset in range(7):
            stamp = week_start + pd.Timedelta(days=offset)
            day = np.datetime64(stamp.date(), "D")
            if stamp.dayofweek == 2:
                missing[int((day - np.datetime64("2025-01-06", "D")).astype(int))] = True
        if generator.random() < 0.5:
            continue
        for offset in range(5):
            stamp = week_start + pd.Timedelta(days=offset)
            if not cal.is_workday([np.datetime64(stamp.date(), "D")])[0]:
                continue
            for _ in range(3):
                rows.append(dict(date=stamp, direction=0, amount=25.0, category="sales", counterparty=""))
    history = _history("2025-01-06", 91, rows, missing=missing)
    model = Model().fit([history])
    paths = model.sample(history, 28, 6, np.random.default_rng(2))

    assert paths.diagnostics["weekly_dependence"] > 0.2
    # Every Wednesday is unknown, so no donor week can cover a target Wednesday.
    assert paths.diagnostics["week_blocks_unavailable"] is True
    assert paths.diagnostics["donor_mode"] == "day"
    # Wednesday targets fall back to a relaxed weekday donor, and that is reported.
    assert paths.diagnostics["donor_source_counts"]["weekday_relaxed"] > 0
    assert len(paths.events) > 0


def test_stationary_stream_keeps_its_amounts_and_a_unit_factor():
    history = _constant_history()
    assert blocks._level_factor(history, 0) == 1.0
    assert blocks._level_factor(history, 1) == 1.0

    paths = Model().fit([history]).sample(history, 20, 8, np.random.default_rng(3))
    assert paths.diagnostics["level_factor"] == {"0": 1.0, "1": 1.0}
    expected = np.where(paths.events.direction.to_numpy(int) == 0, 100.0, 40.0)
    assert len(expected) > 0
    np.testing.assert_allclose(paths.events.amount.to_numpy(float), expected, rtol=0, atol=1e-9)


def test_recent_drift_raises_the_factor_within_its_clip(monkeypatch):
    history = _drift_history()
    factor = blocks._level_factor(history, 0)
    assert 1.0 < factor <= 1.25
    # A direction with no positive amounts at all stays untouched.
    assert blocks._level_factor(history, 1) == 1.0

    paths = Model().fit([history]).sample(history, 30, 10, np.random.default_rng(1))
    assert paths.diagnostics["level_factor"] == {"0": factor, "1": 1.0}

    monkeypatch.setattr(blocks, "_level_factor", lambda history, direction: 1.0)
    baseline = Model().fit([history]).sample(history, 30, 10, np.random.default_rng(1))
    assert len(paths.events) == len(baseline.events) > 0
    assert paths.events.amount.sum() > baseline.events.amount.sum()


def test_level_correction_scales_amounts_once_and_leaves_everything_else(monkeypatch):
    history = _drift_history()
    paths = Model().fit([history]).sample(history, 30, 10, np.random.default_rng(1))

    monkeypatch.setattr(blocks, "_level_factor", lambda history, direction: 1.0)
    baseline = Model().fit([history]).sample(history, 30, 10, np.random.default_rng(1))
    for key in ("path", "day", "direction", "category", "counterparty"):
        np.testing.assert_array_equal(paths.events[key].to_numpy(), baseline.events[key].to_numpy())

    level = paths.diagnostics["level_factor"]
    applied = np.array([level[str(direction)] for direction in baseline.events.direction.to_numpy(int)])
    assert (applied != 1.0).any(), "the drift fixture must exercise a non-unit factor"
    np.testing.assert_allclose(paths.events.amount.to_numpy(float),
                               baseline.events.amount.to_numpy(float) * applied, rtol=1e-12)


def test_sparse_and_empty_directions_fall_back_to_a_unit_factor():
    rows = [dict(date=pd.Timestamp(day), direction=0, amount=100.0, category="sales", counterparty="shop")
            for day in _workdays("2024-01-01", 120)]
    sparse = _workdays("2024-01-01", 120)[:3]
    rows += [dict(date=pd.Timestamp(day), direction=1, amount=amount, category="buy", counterparty="supplier")
             for day, amount in zip(sparse, (5.0, 6.0, 900.0))]
    history = _history("2024-01-01", 120, rows)

    # Three positive outflows are below the eight-observation minimum.
    assert blocks._level_factor(history, 1) == 1.0
    paths = Model().fit([history]).sample(history, 20, 6, np.random.default_rng(0))
    assert paths.diagnostics["level_factor"]["1"] == 1.0

    empty = _history("2024-04-01", 40, [])
    assert blocks._level_factor(empty, 0) == 1.0 and blocks._level_factor(empty, 1) == 1.0
    silent = Model().fit([]).sample(empty, 20, 4, np.random.default_rng(0))
    assert silent.diagnostics["level_factor"] == {"0": 1.0, "1": 1.0}
    assert len(silent.events) == 0


def test_month_phase_helper_prefers_the_same_month_position():
    np.testing.assert_array_equal(blocks._month_phase(np.array([1, 10, 11, 20, 21, 31])),
                                  np.array([0, 0, 1, 1, 2, 2]))
    same = blocks._phase_weights(12, np.array([14]))[0]
    adjacent = blocks._phase_weights(12, np.array([19]))[0]
    opposite = blocks._phase_weights(12, np.array([25]))[0]
    assert same > adjacent > opposite > 0.0

    weights = blocks._mixed_weights(blocks._phase_weights(12, np.array([5, 12, 25])))
    assert (weights > 0).all(), "the uniform half keeps every donor possible"
    np.testing.assert_allclose(weights.sum(), 1.0)


def test_month_phase_weighting_concentrates_a_monthly_payment(monkeypatch):
    history = _monthly_history()
    assert set(history.events.date.dt.day) == {5}
    shares = {}
    for weight in (0.0, 0.5):
        monkeypatch.setattr(blocks, "PHASE_WEIGHT", weight)
        paths = Model().fit([history]).sample(history, 62, 40, np.random.default_rng(4))
        assert paths.diagnostics["phase_weight"] == weight
        day_of_month = paths.dated_events().date.dt.day.to_numpy()
        assert len(day_of_month) > 20
        shares[weight] = float((day_of_month <= 10).mean())

    # Uniform weekday matching spreads the rent over the month; the phase score
    # pulls it back toward the first dekad the donor payments actually sit in.
    assert shares[0.0] < 0.45
    assert shares[0.5] > shares[0.0] + 0.1


def test_masked_donor_days_never_reach_the_output(monkeypatch):
    start, days = "2025-01-01", 200
    missing = np.zeros(days, dtype=bool)
    rows = []
    for day in _workdays(start, days):
        offset = int((day - np.datetime64(start, "D")).astype(int))
        if offset % 17 == 3:
            missing[offset] = True
            rows.append(dict(date=pd.Timestamp(day), direction=0, amount=70.0,
                             category="masked_donor", counterparty=""))
        else:
            rows.append(dict(date=pd.Timestamp(day), direction=0, amount=40.0,
                             category="visible", counterparty=""))
    history = _history(start, days, rows, missing=missing)
    assert "masked_donor" not in set(history.events.category.astype(str))

    model = Model().fit([history])
    admissible = history.dates[history.known & history.allowed(history.dates)]
    assert np.isin(model.global_pool.store.dates[model.global_pool.day_blocks], admissible).all()
    for weight in (0.0, 0.5):
        monkeypatch.setattr(blocks, "PHASE_WEIGHT", weight)
        paths = model.sample(history, 45, 12, np.random.default_rng(2))
        assert set(paths.events.category.astype(str)) == {"visible"}
        allowed = history.allowed(_target(history, 45))
        assert np.isin(paths.events.day.to_numpy(int) - 1, np.flatnonzero(allowed)).all()


def test_phase_and_level_correction_stay_deterministic():
    history = _varied_history()
    model = Model().fit([history])
    first = model.sample(history, 40, 12, np.random.default_rng(17))
    second = model.sample(history, 40, 12, np.random.default_rng(17))
    pd.testing.assert_frame_equal(first.events, second.events)
    assert first.diagnostics == second.diagnostics

    other = model.sample(history, 40, 12, np.random.default_rng(18))
    assert not other.events.equals(first.events)
    assert len(other.events) and len(first.events)

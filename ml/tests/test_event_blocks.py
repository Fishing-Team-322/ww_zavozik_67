"""Behavioural tests for the whole-event block resampling forecaster.

All fixtures are tiny synthetic histories; none of them is evaluation data.
"""
import numpy as np
import pandas as pd
import pytest

from tests.event_forecaster_fixtures import histories
from zavozik_ml import calendar as cal
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

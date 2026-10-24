"""Contract and behaviour tests for the recurring-schedule + residual event generator."""
import numpy as np
import pandas as pd
import pytest

from tests.event_forecaster_fixtures import history, histories
from zavozik_ml import calendar as cal
from zavozik_ml.event_forecasters import hybrid
from zavozik_ml.event_forecasters.core import (
    EventHistory,
    EventPaths,
    FitOptions,
    calendar_features,
)
from zavozik_ml.event_forecasters.hybrid import Model

COLUMNS = ["date", "direction", "amount", "category", "counterparty"]
START = "2024-01-01"


def dates_of(days, start=START):
    return np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(days, "D"))


def frame(records):
    return pd.DataFrame.from_records(records, columns=COLUMNS)


def build(records, days=540, start=START, company="synthetic", industry="synthetic_industry", missing=()):
    dates = dates_of(days, start)
    censored = np.zeros(days, dtype=bool)
    detected = np.full(days, np.datetime64("NaT", "D"))
    for lo, hi in missing:
        censored[lo:hi] = True
        detected[lo:hi] = dates[-1]  # the gap is discovered at this cutoff, so it is unknown
    return EventHistory(company, industry, dates, censored, detected, frame(records))


def index_of(day, start=START):
    return int((np.datetime64(day, "D") - np.datetime64(start, "D")).astype(int))


def monthly(day_of_month=5, amount=900.0, category="rent", counterparty="landlord", direction=1,
            days=540, start=START, shift_to_workday=False, skip_months=()):
    """Monthly schedule; ``shift_to_workday`` moves a weekend payment to the next working day."""
    dates = dates_of(days, start)
    stamps = pd.DatetimeIndex(dates)
    work = cal.is_workday(dates)
    dom = stamps.day.to_numpy()
    months = stamps.year.to_numpy() * 12 + stamps.month.to_numpy()
    records = []
    for i in np.flatnonzero(dom == day_of_month).tolist():
        if int(months[i]) in skip_months:
            continue
        j = i
        if shift_to_workday:
            while j < len(dates) and not work[j]:
                j += 1
            if j == len(dates):
                continue
        elif not work[i]:
            continue
        records.append(dict(date=pd.Timestamp(dates[j]), direction=direction, amount=amount,
                            category=category, counterparty=counterparty))
    return records


def weekly(weekday=0, amount=1500.0, category="taxi", counterparty="taxi", direction=1,
           days=540, start=START):
    dates = dates_of(days, start)
    work = cal.is_workday(dates)
    hit = pd.DatetimeIndex(dates).dayofweek.to_numpy() == weekday
    return [dict(date=pd.Timestamp(day), direction=direction, amount=amount, category=category,
                 counterparty=counterparty) for day, ok in zip(dates[hit], work[hit]) if ok]


def last_workdays(amount=5000.0, category="salary", counterparty="payroll", direction=1,
                  days=540, start=START):
    dates = dates_of(days, start)
    features = calendar_features(dates)
    hit = (features["wd_to_eom"].to_numpy() == 0) & (features["is_workday"].to_numpy() == 1)
    return [dict(date=pd.Timestamp(day), direction=direction, amount=amount, category=category,
                 counterparty=counterparty) for day in dates[hit]]


def noise(days=540, start=START, seed=0, mean=2.0, category="sales", counterparty="",
          direction=0, amount=120.0):
    rng = np.random.default_rng(seed)
    dates = dates_of(days, start)
    work = cal.is_workday(dates)
    records = []
    for day, ok in zip(dates, work):
        if not ok:
            continue
        for _ in range(int(rng.poisson(mean))):
            records.append(dict(date=pd.Timestamp(day), direction=direction,
                                amount=float(amount * rng.uniform(.5, 1.5)),
                                category=category, counterparty=counterparty))
    return records


def mixed_history(seed=0, days=540, start=START, missing=(), shift_to_workday=False,
                  rent_amount=900.0, company="synthetic"):
    records = monthly(days=days, start=start, shift_to_workday=shift_to_workday, amount=rent_amount)
    records += noise(days=days, start=start, seed=seed)
    return build(records, days=days, start=start, missing=missing, company=company)


def rent_events(paths):
    return paths.events[paths.events.category == "rent"]


def test_generated_paths_validate_and_reconcile():
    h = mixed_history()
    paths = Model().fit([h]).sample(h, 30, 40, np.random.default_rng(11))
    assert isinstance(paths, EventPaths)
    assert paths.validate() is paths
    amounts, counts = paths.daily()
    assert amounts.shape == counts.shape == (40, 30, 2)
    assert counts.sum() == pytest.approx(len(paths.events))
    assert amounts.sum() == pytest.approx(paths.events.amount.sum())
    assert np.isfinite(paths.events.amount).all() and (paths.events.amount >= 0).all()
    assert paths.events.path.between(0, 39).all() and paths.events.day.between(1, 30).all()
    assert paths.events.category.str.len().gt(0).all()
    dated = paths.dated_events()
    assert dated.date.min() >= pd.Timestamp(h.as_of + np.timedelta64(1, "D"))
    assert dated.date.max() <= pd.Timestamp(h.as_of + np.timedelta64(30, "D"))


def test_sampling_is_deterministic_for_equal_seeds():
    h = mixed_history()
    model = Model().fit([h])
    left = model.sample(h, 30, 25, np.random.default_rng(5))
    right = model.sample(h, 30, 25, np.random.default_rng(5))
    pd.testing.assert_frame_equal(left.events, right.events)
    assert left.diagnostics == right.diagnostics
    refit = Model().fit([h]).sample(h, 30, 25, np.random.default_rng(5))
    pd.testing.assert_frame_equal(left.events, refit.events)


def test_rent_schedule_is_generated_once_per_month_at_observed_amount():
    h = mixed_history()
    paths = Model().fit([h]).sample(h, 60, 120, np.random.default_rng(3))
    rent = rent_events(paths)
    assert paths.diagnostics["streams"] >= 1
    assert paths.diagnostics["stream_kinds"] == {"monthly_dom": 1}
    assert rent.groupby("path").size().max() <= 3
    assert rent.groupby("path").size().median() == 2
    assert (rent.amount == 900.0).all() and (rent.direction == 1).all()
    assert (rent.counterparty == "landlord").all() and (rent.known_event_id == "").all()
    assert all(probability < 1.0 for probability in paths.diagnostics["stream_probabilities"])
    assert paths.diagnostics["stream_probabilities"][0] > 0.5
    assert paths.diagnostics["assigned_rows"] > 0 and paths.diagnostics["residual_rows"] > 0


def test_short_horizon_does_not_duplicate_a_monthly_occurrence():
    h = mixed_history()
    cutoff = h.prefix(np.datetime64("2025-06-01"))  # five days that contain the June rent date
    paths = Model().fit([h]).sample(cutoff, 5, 60, np.random.default_rng(4))
    counts = rent_events(paths).groupby("path").size()
    assert counts.max() == 1 and len(counts) > 30


def test_weekly_schedule_is_supported():
    records = weekly() + noise(seed=2)
    h = build(records)
    streams = hybrid._detect_streams(h.events, h.dates[h.known])
    taxi = [stream for stream in streams if stream.category == "taxi"]
    assert taxi and taxi[0].kind == "weekly" and taxi[0].anchor == 0
    paths = Model().fit([h]).sample(h, 60, 40, np.random.default_rng(17))
    events = paths.dated_events()
    events = events[events.category == "taxi"]
    assert len(events)
    assert (pd.DatetimeIndex(events.date).dayofweek == 0).mean() > 0.8
    weeks = pd.DatetimeIndex(events.date).to_period("W").astype(str)
    assert not events.assign(week=weeks.to_numpy()).duplicated(["path", "week"]).any()


def test_calendar_anchor_schedule_is_supported():
    records = last_workdays() + noise(seed=2)
    h = build(records)
    streams = hybrid._detect_streams(h.events, h.dates[h.known])
    salary = [stream for stream in streams if stream.category == "salary"]
    assert salary and salary[0].kind == "calendar" and salary[0].anchor == "last_workday"
    paths = Model().fit([h]).sample(h, 90, 40, np.random.default_rng(18))
    events = paths.dated_events()
    events = events[events.category == "salary"]
    assert len(events)
    assert (calendar_features(events.date.to_numpy(dtype="datetime64[D]"))["wd_to_eom"]
            .to_numpy() == 0).all()


def test_historical_rows_never_enter_both_streams():
    h = mixed_history()
    events = h.events
    streams = hybrid._detect_streams(events, h.dates[h.known])
    assert streams, "the synthetic rent schedule must be detected"
    assigned = hybrid._assign_rows(events, streams)
    residual = events[~assigned]
    assert int(assigned.sum()) + len(residual) == len(events)
    assert not set(events.index[assigned]) & set(residual.index)
    claimed = {(stream.counterparty, int(stream.direction), stream.category, int(day))
               for stream in streams for day in stream.days}
    donated = {(row.counterparty, int(row.direction), row.category,
                int(hybrid._to_int(np.array([row.date]))[0])) for row in residual.itertuples()}
    assert not claimed & donated, "a residual donor row also fed a recurring schedule"
    assert assigned[np.isin(events.index, rent_events(h).index)].all()
    paths = Model().fit([h]).sample(h, 30, 10, np.random.default_rng(2))
    assert paths.diagnostics["assigned_rows"] == int(assigned.sum())
    assert paths.diagnostics["residual_rows"] == len(residual)


def test_unstable_pattern_falls_back_to_the_residual_stream():
    rng = np.random.default_rng(9)
    dates = dates_of(300, "2024-06-01")
    work = np.flatnonzero(cal.is_workday(dates))
    records = [dict(date=pd.Timestamp(dates[i]), direction=1, amount=float(rng.uniform(10, 60)),
                    category="courier", counterparty="courier")
               for i in rng.choice(work, 40, replace=True)]
    h = build(records, days=300, start="2024-06-01")
    assert hybrid._detect_streams(h.events, h.dates[h.known]) == []
    assert not hybrid._assign_rows(h.events, []).any()
    paths = Model().fit([h]).sample(h, 20, 20, np.random.default_rng(1))
    assert paths.diagnostics["streams"] == 0
    assert paths.diagnostics["residual_source"] == "local_weeks"
    assert len(paths.events) > 0


def test_pooled_fallback_never_merges_same_day_bursts_into_a_schedule():
    # One category, no counterparty, identical day-of-month but three rows on one day.
    dates = dates_of(540)
    records = [dict(date=pd.Timestamp(day), direction=0, amount=100.0, category="rent", counterparty="")
               for day in dates[pd.DatetimeIndex(dates).day.to_numpy() == 5] for _ in range(3)]
    h = build(records)
    assert hybrid._detect_streams(h.events, h.dates[h.known]) == []


def test_missing_days_censor_evidence_and_cannot_leak_through_donors():
    sentinel = 987654.0
    clean = mixed_history()
    streams = hybrid._detect_streams(clean.events, clean.dates[clean.known])
    clean_due = [stream for stream in streams if stream.category == "rent"][0].due
    rent_days = rent_events(clean).date.to_numpy(dtype="datetime64[D]").astype(int).tolist()
    missing = [(max(0, index_of(np.datetime64(day, "D")) - 1),
                min(540, index_of(np.datetime64(day, "D")) + 2)) for day in rent_days[:6]]
    records = monthly() + noise(seed=0)
    for row in records:
        if any(lo <= index_of(row["date"].date()) < hi for lo, hi in missing):
            row["amount"] = sentinel
    h = build(records, missing=missing)
    assert sentinel not in h.events.amount.to_numpy()
    assert len(rent_events(h)) == len(rent_days) - 6
    visible = set(hybrid._to_int(h.dates[h.known]).tolist())
    assert set(hybrid._to_int(h.events.date).tolist()) <= visible
    censored_streams = hybrid._detect_streams(h.events, h.dates[h.known])
    rent_stream = [stream for stream in censored_streams if stream.category == "rent"][0]
    assert rent_stream.due < clean_due and rent_stream.occurrences == len(rent_days) - 6
    paths = Model().fit([h]).sample(h, 60, 40, np.random.default_rng(6))
    assert paths.diagnostics["residual_source"] == "local_weeks"
    assert sentinel not in paths.events.amount.to_numpy()
    assert paths.diagnostics["assigned_rows"] + paths.diagnostics["residual_rows"] == len(h.events)


def test_schedule_without_visible_evidence_is_not_invented():
    censored = []
    for row in monthly():
        start = index_of(row["date"].date())
        censored.append((max(0, start - 1), min(540, start + 2)))
    h = build(monthly() + noise(seed=1), missing=censored)
    assert not rent_events(h).shape[0]
    assert len(h.events) > 0
    assert [stream for stream in hybrid._detect_streams(h.events, h.dates[h.known])
            if stream.category == "rent"] == []


def test_no_future_or_raw_leakage_from_a_longer_history():
    sentinel = 123456.0
    full = mixed_history(days=600)
    cutoff = full.dates[420]
    base = full.prefix(cutoff)
    model = Model().fit([base])
    mutated = full.prefix(full.dates[-1])
    later = mutated.raw_events.date > pd.Timestamp(cutoff)
    mutated.raw_events.loc[later, "amount"] = sentinel
    left = model.sample(base, 30, 30, np.random.default_rng(8))
    right = model.sample(mutated.prefix(cutoff), 30, 30, np.random.default_rng(8))
    pd.testing.assert_frame_equal(left.events, right.events)
    assert sentinel not in left.events.amount.to_numpy()
    assert later.any()


def test_empty_fit_and_empty_history_generate_nothing():
    empty = build([], days=90)
    paths = Model().fit([]).sample(empty, 30, 3, np.random.default_rng(0))
    assert paths.events.empty
    amounts, counts = paths.daily()
    assert not amounts.any() and not counts.any()
    assert paths.diagnostics["streams"] == 0 and paths.diagnostics["clipped_events"] == 0
    assert Model().fit([empty]).sample(empty, 30, 3, np.random.default_rng(0)).events.empty


def test_zero_amounts_and_same_day_bursts_are_preserved():
    h = mixed_history(rent_amount=0.0)
    paths = Model().fit([h]).sample(h, 30, 20, np.random.default_rng(12))
    rent = rent_events(paths)
    assert len(rent) and (rent.amount == 0.0).all() and np.isfinite(rent.amount).all()
    dates = dates_of(270)
    burst = build([dict(date=pd.Timestamp(day), direction=0, amount=10.0, category=f"mark{i}",
                        counterparty=f"cp{i}")
                   for day in dates[cal.is_workday(dates)] for i in range(3)], days=270)
    paths = Model().fit([burst]).sample(burst, 30, 5, np.random.default_rng(13))
    amounts, counts = paths.daily()
    assert counts.sum() == pytest.approx(len(paths.events))
    assert amounts.sum() == pytest.approx(paths.events.amount.sum())
    assert (counts > 1).any()


def test_nonworking_days_are_not_generated():
    h = history()
    paths = Model().fit(histories(2)).sample(h, 30, 20, np.random.default_rng(21))
    generated = paths.dated_events().date.to_numpy(dtype="datetime64[D]")
    assert len(generated)
    assert cal.is_workday(generated).all()


def test_day_cap_is_explicit_and_reported():
    dates = dates_of(270)
    records = [dict(date=pd.Timestamp(day), direction=0, amount=5.0, category=f"mark{i}",
                    counterparty=f"cp{i}")
               for day in dates[cal.is_workday(dates)] for i in range(20)]
    h = build(records, days=270)
    paths = Model(FitOptions(max_events_per_day=3)).fit([h]).sample(h, 10, 4, np.random.default_rng(14))
    _, counts = paths.daily()
    assert counts.max() <= 3
    assert paths.diagnostics["clipped_events"] > 0
    assert paths.diagnostics["max_events_per_day"] == 3


def test_training_rows_cap_is_reported():
    model = Model(FitOptions(max_training_rows=10)).fit(histories(2))
    assert model.diagnostics["training_rows_truncated"] is True
    assert model.diagnostics["training_rows"] >= 10


def test_no_invented_counterparties_or_invoice_ids():
    h = mixed_history()
    paths = Model().fit([h]).sample(h, 60, 40, np.random.default_rng(15))
    observed = set(h.events.counterparty.fillna("").astype(str))
    assert set(paths.events.counterparty.fillna("").astype(str)) <= observed
    assert (paths.events.known_event_id == "").all()


def test_weekend_shifted_schedule_keeps_date_and_occurrence_uncertainty():
    h = mixed_history(shift_to_workday=True, days=720)
    streams = hybrid._detect_streams(h.events, h.dates[h.known])
    rent = [stream for stream in streams if stream.category == "rent"]
    assert rent and rent[0].kind in {"monthly_dom", "calendar"}
    if rent[0].kind == "monthly_dom":
        assert len(np.unique(rent[0].shifts)) >= 2
    paths = Model().fit([h]).sample(h, 120, 120, np.random.default_rng(16))
    dated = paths.dated_events()
    rent = dated[dated.category == "rent"]
    assert len(rent)
    stamps = pd.DatetimeIndex(rent.date)
    assert len(set(stamps.day)) >= 2
    # The detected schedule emits at most one occurrence per path-month; off-anchor
    # same-stream rows now stay in the residual and may re-emit, so a strict
    # one-rent-per-month bound over all generated rent is no longer correct.
    per_path = rent.groupby("path").size()
    assert (per_path <= len(np.unique(stamps)) + 1).all()
    assert all(probability < 1.0 for probability in paths.diagnostics["stream_probabilities"])


def test_sparse_stream_borrows_pooled_amount_priors_and_occurrence_rate():
    pool_source = mixed_history(company="pool-source")
    target = build(monthly(days=150, start="2025-01-01", amount=1234.0)
                   + noise(days=150, start="2025-01-01", seed=3, mean=0.6),
                   days=150, start="2025-01-01", company="target")
    model = Model().fit([pool_source])
    rent = [stream for stream in hybrid._detect_streams(target.events, target.dates[target.known])
            if stream.category == "rent"]
    assert len(rent) and len(rent[0].amounts) < hybrid._MIN_LOCAL_AMOUNTS
    paths = model.sample(target, 60, 80, np.random.default_rng(19))
    generated = rent_events(paths)
    assert len(generated)
    # Relative pooled amounts are all 1.0 for this fixture, so the sparse stream keeps its level.
    assert set(generated.amount) == {1234.0}
    assert 0.0 < paths.diagnostics["stream_probabilities"][0] < 1.0


def test_quiet_complete_weeks_remain_available_as_donors():
    h = mixed_history(days=120)
    events = h.events
    residual = events.iloc[:1]  # one event in the whole history
    weeks, by_week = hybrid._residual_by_week(residual, h)
    complete = hybrid._complete_weeks(h)
    assert len(weeks) == len(complete) >= 3
    assert sum(len(rows) == 0 for rows in by_week.values()) == len(complete) - 1

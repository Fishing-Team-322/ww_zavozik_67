"""Behaviour tests for the renewal hazard benchmark; synthetic fixtures only."""
import numpy as np
import pandas as pd
import pytest

from zavozik_ml import calendar as cal
from zavozik_ml.event_forecasters import renewal
from zavozik_ml.event_forecasters.core import EventHistory, EventPaths, FitOptions
from zavozik_ml.event_forecasters.renewal import Model, _activation_rows

FAST = FitOptions(rounds=10, threads=1, max_training_rows=20_000, seed=11, max_events_per_day=8)
TABLE = FitOptions(rounds=0, threads=1, max_training_rows=20_000, seed=11, max_events_per_day=8)


def frame(records):
    return pd.DataFrame(records, columns=["date", "direction", "amount", "category", "counterparty"])


def steady_history(days=168, seed=5, company_id="steady", inflow=2, outflow=1, purchase_amount=90.0):
    """Workday-only company: constant multiplicity streams plus a monthly rent."""
    rng = np.random.default_rng(seed)
    dates = np.arange(np.datetime64("2025-01-01"),
                      np.datetime64("2025-01-01") + np.timedelta64(days, "D"))
    work = cal.is_workday(dates)
    records = []
    for i, day in enumerate(dates):
        if not work[i]:
            continue
        stamp = pd.Timestamp(day)
        for _ in range(inflow):
            records.append(dict(date=stamp, direction=0, amount=float(rng.gamma(3, 100)),
                                category="sales", counterparty=""))
        for _ in range(outflow):
            records.append(dict(date=stamp, direction=1, amount=float(rng.gamma(2, purchase_amount)),
                                category="purchase", counterparty=""))
        if stamp.day == 5:
            records.append(dict(date=stamp, direction=1, amount=500.0, category="rent",
                                counterparty="landlord"))
    return EventHistory(company_id, "renewal_industry", dates, np.zeros(days, dtype=bool),
                        np.full(days, np.datetime64("NaT", "D")), frame(records))


def blank_history(days=40, company_id="blank"):
    dates = np.arange(np.datetime64("2025-01-01"),
                      np.datetime64("2025-01-01") + np.timedelta64(days, "D"))
    return EventHistory(company_id, "other_industry", dates, np.zeros(days, dtype=bool),
                        np.full(days, np.datetime64("NaT", "D")), frame([]))


def fixture_histories(count=3, **kwargs):
    return [steady_history(seed=seed + 1, company_id=f"fixture-{seed}", **kwargs)
            for seed in range(count)]


def with_extra(history, records):
    return EventHistory(history.company_id, history.industry, history.dates.copy(),
                        history.missing.copy(), history.detected.copy(),
                        pd.concat([history.raw_events, frame(records)], ignore_index=True))


def test_sampled_paths_reconcile_with_daily_totals():
    histories = fixture_histories(3)
    model = Model(FAST).fit(histories)
    paths = model.sample(histories[0], 30, 12, np.random.default_rng(3))
    assert isinstance(paths, EventPaths)
    assert paths.origin == histories[0].as_of and paths.horizon == 30 and paths.n_paths == 12
    amounts, counts = paths.daily()
    assert amounts.shape == counts.shape == (12, 30, 2)
    assert counts.sum() == len(paths.events)
    assert amounts.sum() == pytest.approx(paths.events.amount.to_numpy(float).sum())
    totals = paths.events.groupby(["path", "day", "direction"], observed=True).agg(
        events=("amount", "size"), total=("amount", "sum"))
    assert len(totals) > 0
    for (path, day, direction), row in totals.iterrows():
        assert counts[path, day - 1, direction] == row.events
        assert amounts[path, day - 1, direction] == pytest.approx(row.total)


def test_sampling_is_reproducible_for_a_fixed_seed():
    histories = fixture_histories(3)
    model = Model(FAST).fit(histories)
    refit = Model(FAST).fit(histories)
    assert model.diagnostics == refit.diagnostics
    left = model.sample(histories[0], 20, 15, np.random.default_rng(7))
    again = refit.sample(histories[0], 20, 15, np.random.default_rng(7))
    other = model.sample(histories[0], 20, 15, np.random.default_rng(8))
    pd.testing.assert_frame_equal(left.events, again.events)
    assert not left.events.amount.equals(other.events.amount)


def test_generated_events_are_finite_nonnegative_and_marked():
    histories = fixture_histories(3)
    paths = Model(FAST).fit(histories).sample(histories[0], 20, 10, np.random.default_rng(5))
    events = paths.events
    assert len(events) > 0
    assert np.isfinite(events.amount.to_numpy(float)).all() and (events.amount >= 0).all()
    assert events.direction.isin([0, 1]).all()
    assert events.day.between(1, 20).all() and events.path.between(0, 9).all()
    assert (events.category.astype(str).str.len() > 0).all()


def test_no_invented_counterparty_or_event_id():
    histories = fixture_histories(2)
    paths = Model(FAST).fit(histories).sample(histories[0], 20, 8, np.random.default_rng(2))
    events = paths.events
    assert len(events) > 0
    assert (events.counterparty.astype(str) == "").all()
    assert (events.known_event_id.astype(str) == "").all()


def test_same_day_multiplicity_follows_observed_counts():
    histories = fixture_histories(2)
    paths = Model(FAST).fit(histories).sample(histories[0], 20, 12, np.random.default_rng(4))
    events = paths.events
    sales = events[events.category == "sales"].groupby(["path", "day"], observed=True).size()
    purchase = events[events.category == "purchase"].groupby(["path", "day"], observed=True).size()
    assert len(sales) > 0 and set(sales.unique()) == {2}
    assert len(purchase) > 0 and set(purchase.unique()) == {1}


def test_zero_amount_stream_keeps_zero_amounts():
    histories = fixture_histories(2, purchase_amount=0.0)
    model = Model(FAST).fit(histories)
    paths = model.sample(histories[0], 20, 10, np.random.default_rng(6))
    events = paths.events
    assert len(events[events.category == "purchase"]) > 0
    assert (events[events.category == "purchase"].amount == 0.0).all()
    assert events[events.category == "sales"].amount.min() > 0.0


def test_calendar_mask_skips_nonworking_days():
    histories = fixture_histories(3)
    history = histories[0]
    paths = Model(FAST).fit(histories).sample(history, 30, 15, np.random.default_rng(1))
    horizon = history.as_of + np.arange(1, 31) * np.timedelta64(1, "D")
    assert (~cal.is_workday(horizon)).sum() >= 6
    generated = paths.dated_events().date.to_numpy(dtype="datetime64[D]")
    assert len(generated) > 0 and cal.is_workday(generated).all()


def test_missing_exposure_breaks_and_reanchors_renewal_age():
    history = steady_history(days=200)
    history.missing[60:64] = True
    history.detected[60:64] = history.dates[90]
    streams, _ = renewal._select_streams([history])
    rows = _activation_rows(history, streams)
    sales = streams.index((0, "sales"))

    expected = history.known & history.allowed(history.dates)
    expected[:renewal.WARMUP_DAYS] = False
    np.testing.assert_array_equal(rows["keep"], expected)
    assert not rows["age_known"][60:64, sales].any()

    last_before = np.flatnonzero(rows["active"][:60, sales])[-1]
    previous = np.flatnonzero(rows["active"][:last_before, sales])[-1]
    assert rows["age"][last_before, sales] == last_before - previous  # own event excluded
    resumed = np.flatnonzero(rows["active"][64:, sales])[0] + 64
    assert not rows["age_known"][resumed, sales]      # age is censored by the gap
    assert rows["age"][resumed, sales] == resumed - last_before
    assert rows["age_known"][resumed + 1, sales]      # observed event reanchors the clock


def test_events_on_unknown_days_never_reach_sampling():
    history = steady_history(days=150)
    history.missing[70:76] = True
    history.detected[70:76] = history.dates[110]
    tampered = with_extra(history, [
        dict(date=pd.Timestamp(day), direction=0, amount=1e9, category="sales", counterparty="")
        for day in history.dates[70:76]])
    model = Model(FAST).fit(fixture_histories(3))
    left = model.sample(history, 20, 20, np.random.default_rng(4))
    right = model.sample(tampered, 20, 20, np.random.default_rng(4))
    pd.testing.assert_frame_equal(left.events, right.events)
    assert left.diagnostics["events"] == right.diagnostics["events"]


def test_target_day_events_do_not_enter_own_features():
    history = steady_history(days=140)
    streams, _ = renewal._select_streams([history])
    rent = streams.index((1, "rent"))
    base = _activation_rows(history, streams)
    target = next(i for i in range(renewal.WARMUP_DAYS + 5, len(history.dates))
                  if base["active"][i, rent])
    keep = ~((history.raw_events.date == pd.Timestamp(history.dates[target]))
             & (history.raw_events.category == "rent"))
    trimmed = EventHistory(history.company_id, history.industry, history.dates.copy(),
                           history.missing.copy(), history.detected.copy(),
                           history.raw_events[keep].reset_index(drop=True))
    other = _activation_rows(trimmed, streams)
    assert base["active"][target, rent] and not other["active"][target, rent]
    for key in ("age", "age_known", "active_30", "known_30", "rate_30"):
        np.testing.assert_array_equal(base[key][target, rent], other[key][target, rent])


def test_fit_reads_only_the_supplied_prefix():
    full = steady_history(days=200)
    cutoff = full.dates[150]
    tampered = full.raw_events.copy()
    later = tampered.date > pd.Timestamp(cutoff)
    tampered.loc[later, "amount"] = tampered.loc[later, "amount"] * 1000.0
    broken = EventHistory(full.company_id, full.industry, full.dates.copy(), full.missing.copy(),
                          full.detected.copy(), tampered)
    neighbour = steady_history(days=200, seed=9, company_id="prefix-neighbour")
    clean = Model(FAST).fit([full.prefix(cutoff), neighbour.prefix(cutoff)])
    dirtied = Model(FAST).fit([broken.prefix(cutoff), neighbour.prefix(cutoff)])
    assert clean.diagnostics == dirtied.diagnostics
    original = full.prefix(cutoff)
    left = clean.sample(original, 20, 20, np.random.default_rng(9))
    right = dirtied.sample(original, 20, 20, np.random.default_rng(9))
    pd.testing.assert_frame_equal(left.events, right.events)


def test_no_fitted_exposure_generates_empty_scenarios():
    blank = blank_history()
    model = Model(FAST).fit([blank])
    assert model.hazard_kind == "empty" and model.streams == []
    paths = model.sample(blank, 10, 3, np.random.default_rng(0))
    assert isinstance(paths, EventPaths) and len(paths.events) == 0
    amounts, counts = paths.daily()
    assert amounts.shape == (3, 10, 2) and not amounts.any() and not counts.any()
    assert len(Model(FAST).fit([]).sample(blank, 5, 2, np.random.default_rng(1)).events) == 0


def test_unseen_company_borrows_pooled_hazard_and_scale():
    model = Model(TABLE).fit(fixture_histories(3))
    blank = blank_history()
    paths = model.sample(blank, 20, 40, np.random.default_rng(2))
    assert len(paths.events) > 0
    amounts = paths.events.amount.to_numpy(float)
    assert np.isfinite(amounts).all() and (amounts >= 0).all()
    assert set(paths.events.category) <= {category for _, category in model.streams}
    used = paths.diagnostics["amount_scale_used"]
    assert used[0] > 1.0  # unit scale of an eventless company replaced by the pooled scale
    assert paths.events[paths.events.direction == 0].amount.median() > 10.0


def test_hazard_ceiling_and_day_cap_are_reported():
    always = steady_history(days=200, seed=3, company_id="always", inflow=1, outflow=1)
    model = Model(TABLE).fit([always, steady_history(days=200, seed=8, company_id="always-2",
                                                     inflow=1, outflow=1)])
    paths = model.sample(always, 15, 20, np.random.default_rng(1))
    assert paths.diagnostics["hazard_clipped"] > 0
    assert paths.diagnostics["events"] > 0
    _, counts = paths.daily()
    assert counts.sum(axis=2).max() <= TABLE.max_events_per_day


def test_hazard_kind_and_horizon_edges():
    histories = fixture_histories(3)
    model = Model(FAST).fit(histories)
    assert model.hazard_kind == ("lightgbm" if renewal.lightgbm is not None else "table")
    assert model.diagnostics["hazard_kind"] == model.hazard_kind
    assert Model(TABLE).fit(histories).hazard_kind == "table"
    history = histories[0]
    single = model.sample(history, 1, 1, np.random.default_rng(0))
    assert single.events.day.between(1, 1).all()
    assert single.daily()[0].shape == (1, 1, 2)
    wide = model.sample(history, 30, 30, np.random.default_rng(0))
    assert wide.dated_events().date.max() <= pd.Timestamp(history.as_of + np.timedelta64(30, "D"))


def test_thin_stream_is_dropped_and_reported():
    base = steady_history(days=150)
    history = with_extra(base, [
        dict(date=pd.Timestamp(base.dates[40]), direction=1, amount=40.0, category="refund",
             counterparty=""),
        dict(date=pd.Timestamp(base.dates[95]), direction=1, amount=40.0, category="refund",
             counterparty=""),
    ])
    streams, dropped = renewal._select_streams([history])
    assert (1, "refund") not in streams and (1, "refund") in dropped
    model = Model(FAST).fit([history])
    assert "1:refund" in model.diagnostics["dropped_streams"]
    assert model.diagnostics["dropped_events"] == 2
    paths = model.sample(history, 20, 10, np.random.default_rng(3))
    assert "refund" not in set(paths.events.category)


def test_regime_terms_form_a_distribution():
    model = Model(FAST).fit(fixture_histories(3))
    assert len(model.regime_probs) == len(model.regime_theta) == len(renewal.REGIME_EDGES) + 1
    assert model.regime_probs.sum() == pytest.approx(1.0)
    assert (model.regime_probs >= 0).all()
    assert np.isfinite(model.regime_theta).all()
    assert (np.abs(model.regime_theta) <= renewal.REGIME_THETA_LIMIT).all()

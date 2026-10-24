"""Contract tests for the small CPU GRU day-resolution event generator."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from tests.event_forecaster_fixtures import histories, history
from zavozik_ml import calendar as cal
from zavozik_ml.event_forecasters import gru
from zavozik_ml.event_forecasters.core import EVENT_COLUMNS, EventHistory, FitOptions

FAST = dict(seed=11, threads=1, epochs=1, max_training_rows=1200, hidden_size=8, max_events_per_day=64)
EVENT_KEYS = ["date", "direction", "amount", "category", "counterparty"]


def _options(**patch):
    return FitOptions(**(FAST | patch))


def _fit(train, **patch):
    return gru.Model(_options(**patch)).fit(train)


def _frame(h, events):
    return EventHistory(h.company_id, h.industry, h.dates.copy(), h.missing.copy(),
                        h.detected.copy(), events[EVENT_KEYS].reset_index(drop=True))


def _prefix(h, index=110):
    return h.prefix(h.dates[index])


def _origin(h):
    return np.asarray(h.as_of, dtype="datetime64[D]")


def _future(h, horizon):
    return _origin(h) + np.arange(1, horizon + 1, dtype=np.int64).astype("timedelta64[D]")


def test_training_and_sampling_reconcile_and_are_deterministic():
    train = histories(n=2, days=120)
    view = _prefix(train[0])
    model = _fit(train)
    paths = model.sample(view, 12, 16, np.random.default_rng(3))
    again = model.sample(view, 12, 16, np.random.default_rng(3))
    assert set(paths.events.columns) == set(EVENT_COLUMNS)
    amounts, counts = paths.daily()
    assert amounts.shape == counts.shape == (16, 12, 2)
    assert np.isfinite(amounts).all() and (amounts >= 0).all()
    filled = np.nonzero(counts)
    assert counts.sum() == len(paths.events)
    np.testing.assert_array_equal(counts[filled], paths.events.groupby(["path", "day", "direction"]).size().to_numpy())
    np.testing.assert_allclose(amounts[filled],
                               paths.events.groupby(["path", "day", "direction"]).amount.sum().to_numpy())
    assert (paths.events.category.astype(str).str.len() > 0).all()
    # no invented identities or invoice links
    assert (paths.events.known_event_id.astype(str) == "").all()
    assert (paths.events.counterparty.astype(str) == "").all()
    pd.testing.assert_frame_equal(paths.events, again.events)
    pd.testing.assert_frame_equal(paths.events, model.sample(view, 12, 16, np.random.default_rng(3)).events)
    # refitting with the same options reproduces the generator exactly
    pd.testing.assert_frame_equal(paths.events, _fit(train).sample(view, 12, 16,
                                                                 np.random.default_rng(3)).events)


def test_multiple_same_day_events_survive_per_path():
    train = histories(n=2, days=120)
    model = _fit(train)
    paths = model.sample(_prefix(train[0]), 20, 40, np.random.default_rng(8))
    per_day = paths.events.groupby(["path", "day"]).size()
    assert per_day.max() >= 2                      # same-day events are kept individually
    _, counts = paths.daily()
    assert int(counts.max()) == int(per_day.max())


def test_history_without_events_trains_and_keeps_amounts_zero():
    empty = _frame(history(days=60), pd.DataFrame(columns=EVENT_KEYS))
    model = _fit([empty])
    assert model.diagnostics["marks"] == ["unknown"]
    seq = model._history_sequence(empty)
    assert not seq["counts"].any()
    targets = model._targets(seq["counts"], seq["marks"], seq["bins"], seq["known"])
    np.testing.assert_array_equal(targets["bucket"], np.zeros(len(targets["bucket"])))
    paths = model.sample(empty, 5, 4, np.random.default_rng(1))
    # no amount donors exist at all, so every sampled event keeps a zero amount
    assert np.isfinite(paths.events.amount).all() and not paths.events.amount.any()
    amounts, counts = paths.daily()
    assert amounts.shape == counts.shape == (4, 5, 2)
    assert not amounts.any()
    assert set(paths.events.category) <= {"unknown"}


def test_missing_days_are_not_zero_events_and_break_targets():
    h = history(days=120)
    h.missing[40:50] = True
    h.detected[40:50] = h.dates[55]
    censored = _prefix(h, 60)
    assert len(censored.raw_events[censored.raw_events.date.isin(pd.to_datetime(censored.dates[40:50]))])
    assert not censored.known[40:50].any()          # incomplete exposure at this cutoff
    model = _fit([censored])
    seq = model._history_sequence(censored)
    assert not seq["known"][40:50].any()
    assert not seq["counts"][40:50].any()           # gap is not an observed silence
    assert not seq["raw"][40:50, 0].any()
    targets = model._targets(seq["counts"], seq["marks"], seq["bins"], seq["known"])
    assert not targets["valid"][40:51].any()        # gaps and the day after them are ungraded
    assert targets["valid"][39] and targets["valid"][51]
    paths = model.sample(censored, 6, 5, np.random.default_rng(2))
    assert paths.diagnostics["observed_context_days"] < paths.diagnostics["context_days"]


def test_teacher_targets_are_shifted_and_never_use_the_graded_day():
    h = history(days=90)
    model = _fit([h])
    base = model._history_sequence(h)
    changed = h.raw_events.copy()
    last = changed.date == pd.Timestamp(h.dates[-1])
    changed.loc[last, "amount"] = changed.loc[last, "amount"] * 3 + 1
    changed.loc[last, "direction"] = 1 - changed.loc[last, "direction"]
    extra = pd.DataFrame([dict(date=pd.Timestamp(h.dates[-1]), direction=1, amount=1234.5,
                               category="rent", counterparty="")] * 2)
    other = model._history_sequence(_frame(h, pd.concat([changed, extra], ignore_index=True)))
    np.testing.assert_array_equal(base["raw"][:-1], other["raw"][:-1])   # inputs end at day t
    assert not np.allclose(base["raw"][-1], other["raw"][-1])
    before = model._targets(base["counts"], base["marks"], base["bins"], base["known"])
    after = model._targets(other["counts"], other["marks"], other["bins"], other["known"])
    np.testing.assert_array_equal(before["valid"][:-1], after["valid"][:-1])
    np.testing.assert_array_equal(before["count"][:-1], after["count"][:-1])
    np.testing.assert_array_equal(before["mark"][:-1], after["mark"][:-1])
    # only the row graded from the changed day moves, and it really moves
    assert before["bucket"][-1] != after["bucket"][-1]
    assert not np.allclose(before["direction"][-1], after["direction"][-1])


def test_targets_cover_empty_days_buckets_and_terminal_horizon():
    h = history(days=120)
    model = _fit([h])
    seq = model._history_sequence(h)
    targets = model._targets(seq["counts"], seq["marks"], seq["bins"], seq["known"])
    total = seq["counts"].sum(axis=1)
    assert not targets["valid"][0]
    assert targets["valid"][1:].all()
    assert targets["valid"][-1]                     # terminal day is still a real target
    np.testing.assert_array_equal(targets["bucket"],
                                  np.minimum(total, model.count_cap).astype(np.int64))
    np.testing.assert_array_equal(targets["count"].argmax(axis=1), targets["bucket"])
    assert (total == 0).any() and (total > 1).any()  # zero-count and multi-event targets exist
    busy = total > 0
    np.testing.assert_allclose(targets["direction"][busy].sum(axis=1), 1.0)
    np.testing.assert_allclose(targets["mark"][busy].sum(axis=(1, 2)), 1.0)


def test_same_day_row_ties_are_permutation_invariant():
    h = history(days=90)
    model = _fit([h])
    base = model._history_sequence(h)
    shuffled = _frame(h, h.raw_events.sample(frac=1.0, random_state=7))
    other = model._history_sequence(shuffled)
    np.testing.assert_array_equal(base["raw"], other["raw"])
    np.testing.assert_array_equal(base["marks"], other["marks"])
    np.testing.assert_array_equal(base["counts"], other["counts"])


def test_prefix_sampling_ignores_undiscovered_tail_records():
    base = history(days=140)
    cutoff = base.dates[100]
    later = base.raw_events.date > pd.Timestamp(cutoff)
    loud = base.raw_events.copy()
    loud.loc[later, "amount"] = loud.loc[later, "amount"] * 40 + 5
    quiet = base.raw_events.copy()
    quiet.loc[later, "amount"] = 0.0
    # tail records exist in raw_events but stay undiscovered at this cutoff
    missing = base.missing.copy()
    detected = base.detected.copy()
    missing[101:] = True
    detected[101:] = base.dates[105]        # gap declared and discovered before the last day

    def censored(events):
        return EventHistory(base.company_id, base.industry, base.dates.copy(), missing.copy(),
                            detected.copy(), events[EVENT_KEYS].reset_index(drop=True))

    loud_view, quiet_view = censored(loud), censored(quiet)
    model = _fit([base.prefix(cutoff)])
    for view in (loud_view, quiet_view):
        seq = model._history_sequence(view)
        assert (seq["dates"] == base.dates).all()
        assert not seq["known"][101:].any()
        assert not seq["counts"][101:].any()        # undiscovered records never enter features
    views = [view.prefix(cutoff) for view in (loud_view, quiet_view)]
    samples = [_fit([view]).sample(view, 10, 8, np.random.default_rng(9)) for view in views]
    pd.testing.assert_frame_equal(samples[0].events, samples[1].events)
    # control: once those same tails are observed the generator does move
    loud_full, quiet_full = _frame(base, loud), _frame(base, quiet)
    assert not loud_full.events.equals(quiet_full.events)
    loud_paths = _fit([loud_full]).sample(loud_full, 10, 8, np.random.default_rng(9))
    quiet_paths = _fit([quiet_full]).sample(quiet_full, 10, 8, np.random.default_rng(9))
    assert not loud_paths.events.equals(quiet_paths.events)


def test_unseen_marks_collapse_to_unknown_slot_in_sequences_and_samples():
    train = history(days=120)
    model = _fit([train])
    extra = pd.DataFrame([dict(date=pd.Timestamp(train.dates[60]), direction=0, amount=50.0,
                               category="mystery", counterparty="")])
    view = _frame(train, pd.concat([train.raw_events, extra], ignore_index=True))
    assert "mystery" not in model.marks
    seq = model._history_sequence(view)
    day = int((np.datetime64(train.dates[60], "D") - train.dates[0]).astype(int))
    assert seq["marks"][day, 0, 0] == 1.0
    paths = model.sample(view, 5, 4, np.random.default_rng(6))
    assert set(paths.events.category) <= set(model.marks)


def test_zero_amount_marks_keep_exact_zero_mass():
    h = history(days=120)
    frame = h.raw_events.copy()
    rent = frame.category == "rent"
    assert rent.any()
    frame.loc[rent, "amount"] = 0.0
    zeroed = _frame(h, frame)
    view = _prefix(zeroed)
    model = _fit([view])
    # fit-only labels: zero amounts land in bin 0, positive ones in later bins
    fitted = zeroed.events
    assert model._event_bins(1, fitted.loc[fitted.category == "rent", "amount"].to_numpy(float)).max() == 0
    assert model._event_bins(1, fitted.loc[fitted.category == "purchase", "amount"].to_numpy(float)).min() >= 1
    assert model._event_bins(0, fitted.loc[fitted.direction == 0, "amount"].to_numpy(float)).min() >= 1
    seq = model._history_sequence(view)
    rent_days = np.flatnonzero(seq["bins"][:, 1, model.mark_index["rent"], 0] > 0)
    assert len(rent_days)
    np.testing.assert_array_equal(seq["bins"][rent_days, 1, model.mark_index["rent"], 1:], 0.0)
    # bin 0 sampling is exact zero mass, not a donor value
    values, missing = model._bin_values(1, np.array([0, 0, 0]), 1000.0, np.random.default_rng(4))
    np.testing.assert_array_equal(values, np.zeros(3))
    assert not missing.any()
    # mark-level empirical pooling stays available as the thin-stream fallback
    pool = model._resolve_amount_pool(view, 1, "rent")
    assert pool.size and not pool.any()
    paths = model.sample(view, 30, 40, np.random.default_rng(4))
    assert np.isfinite(paths.events.amount).all() and (paths.events.amount >= 0).all()


def test_amount_head_is_a_learned_binned_distribution_with_donors():
    train = histories(n=2, days=120)
    model = _fit(train)
    assert model.n_amount_bins == gru._POSITIVE_AMOUNT_BINS + 1
    assert model.net.amount_head.out_features == model.n_marks * 2 * model.n_amount_bins
    assert set(model.amount_pools)                      # fit-only within-bin donors exist
    assert not any(slot == 0 for _, slot in model.amount_pools)   # bin 0 keeps no donors
    for (_, slot), pool in model.amount_pools.items():
        assert slot >= 1 and len(pool) and np.isfinite(pool).all() and (pool > 0).all()
    view = _prefix(train[0])
    paths = model.sample(view, 15, 30, np.random.default_rng(7))
    assert paths.diagnostics["amount_bins"] == model.n_amount_bins
    assert paths.diagnostics["amount_fallback_events"] == 0
    assert paths.diagnostics["zero_amount_events"] == int((paths.events.amount == 0).sum())
    assert np.isfinite(paths.events.amount).all() and (paths.events.amount > 0).sum() > 0


def test_positive_bins_without_donors_report_empirical_fallback():
    h = history(days=120)
    only_zero_out = h.raw_events.copy()
    out = only_zero_out.direction == 1
    only_zero_out.loc[out, "amount"] = 0.0
    zero_out = _frame(h, only_zero_out)
    view = _prefix(zero_out)
    model = _fit([view])
    assert not [key for key in model.amount_pools if key[0] == 1]   # direction 1 has no positive donors
    _, missing = model._bin_values(1, np.array([3, 4, 0]), 100.0, np.random.default_rng(1))
    np.testing.assert_array_equal(missing, np.array([True, True, False]))
    paths = model.sample(view, 20, 20, np.random.default_rng(3))
    assert paths.diagnostics["amount_fallback_events"] >= 0
    assert np.isfinite(paths.events.amount).all() and (paths.events.amount >= 0).all()


def test_nonworking_mask_suppresses_generated_events():
    train = history(days=120)
    view = _prefix(train)
    model = _fit([train])
    paths = model.sample(view, 20, 25, np.random.default_rng(5))
    _, counts = paths.daily()
    off = ~cal.is_workday(_future(view, 20))
    assert off.any()
    assert counts[:, off, :].sum() == 0
    assert paths.diagnostics["masked_day_paths"] >= 0
    on = cal.is_workday(paths.dated_events().date.to_numpy(dtype="datetime64[D]"))
    assert on.all()


def test_count_cap_is_explicit_and_reported():
    train = history(days=120)
    view = _prefix(train)
    model = _fit([train], max_events_per_day=1)
    assert model.count_cap == 1 and model.n_buckets == 2
    paths = model.sample(view, 10, 20, np.random.default_rng(2))
    counts = paths.daily()[1]
    assert counts.max() <= 1
    assert paths.diagnostics["count_cap"] == 1
    assert paths.diagnostics["count_cap_hits"] == int((counts >= 1).sum())


def test_fit_bounds_follow_options():
    train = histories(n=2, days=200)
    small = _fit(train, max_training_rows=50, epochs=3, hidden_size=7)
    assert small.diagnostics["training_rows"] <= 50
    assert small.diagnostics["epochs"] == 3 and small.hidden_size == 7
    assert small.diagnostics["trained"] is True
    big = _fit(train, epochs=99, hidden_size=4096)
    assert big.diagnostics["epochs"] == gru._MAX_EPOCHS
    assert big.hidden_size == gru._MAX_HIDDEN
    assert big.count_cap <= gru._MAX_COUNT_BUCKET
    paths = big.sample(_prefix(train[0]), 3, 2, np.random.default_rng(1))
    assert paths.diagnostics["hidden_size"] == big.hidden_size


def test_cuda_requested_without_cuda_fails_loudly():
    import torch
    if torch.cuda.is_available():
        pytest.skip("this check requires a CUDA-free runtime")
    with pytest.raises(ValueError, match="CUDA was requested"):
        gru.Model(FitOptions(device="cuda"))

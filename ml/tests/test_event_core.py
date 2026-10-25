import numpy as np
import pandas as pd
import pytest

from tests.event_forecaster_fixtures import history
from zavozik_ml.event_forecasters.core import ConditionalAmounts, EventPaths, calendar_features


def test_events_reconcile_with_daily_counts_and_amounts():
    h = history()
    paths = EventPaths.from_records(h, 30, 3, [
        dict(path=0, day=1, direction=0, amount=100., category="sales"),
        dict(path=0, day=1, direction=0, amount=0., category="sales"),
        dict(path=2, day=30, direction=1, amount=70., category="rent"),
    ])
    amounts, counts = paths.daily()
    assert amounts.shape == counts.shape == (3, 30, 2)
    assert amounts.sum() == 170 and counts.sum() == 3
    assert counts[0, 0, 0] == 2
    assert paths.dated_events().date.iloc[-1] == pd.Timestamp(h.as_of + np.timedelta64(30, "D"))


def test_empty_and_invalid_event_paths():
    h = history()
    assert not EventPaths.from_records(h, 30, 2, []).daily()[0].any()
    for patch in (dict(day=0), dict(day=31), dict(path=2), dict(amount=-1.), dict(direction=2), dict(day=1.5)):
        row = dict(path=0, day=1, direction=0, amount=1., category="sales") | patch
        with pytest.raises(ValueError):
            EventPaths.from_records(h, 30, 2, [row])


def test_missing_discovery_is_cutoff_specific():
    h = history()
    h.missing[100:110] = True
    h.detected[100:110] = h.dates[130]
    early = h.prefix(h.dates[120])
    late = h.prefix(h.dates[140])
    assert early.known[100:110].all()
    assert not late.known[100:110].any()
    assert np.isnan(late.daily_counts[100:110]).all()
    # Prefixing a later view must recover information visible at the earlier cutoff.
    assert late.prefix(h.dates[120]).events.equals(early.events)


def test_amount_pool_and_calendar_are_finite_and_deterministic():
    h = history()
    pool = ConditionalAmounts().fit([h.prefix(h.dates[150])])
    a = pool.sample(h.prefix(h.dates[170]), 0, "sales", 100, np.random.default_rng(1))
    b = pool.sample(h.prefix(h.dates[170]), 0, "sales", 100, np.random.default_rng(1))
    np.testing.assert_array_equal(a, b)
    assert np.isfinite(a).all() and (a >= 0).all()
    assert np.isfinite(calendar_features(h.dates).to_numpy()).all()

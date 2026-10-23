from datetime import date, timedelta

import numpy as np

from zavozik_ml import forecasters


def make_history(days: int) -> forecasters.History:
    start = date(2025, 1, 1)
    dates = [start + timedelta(days=i) for i in range(days)]
    weekday = np.array([d.weekday() < 5 for d in dates])
    return forecasters.History(
        dates=dates,
        inflow=np.where(weekday, 100.0, 0.0),
        outflow=np.where(weekday, 40.0, 0.0),
        missing=np.zeros(days, dtype=bool),
    )


def test_naive_respects_weekdays():
    h = make_history(70)
    p = forecasters.get("auto").forecast(h, horizon=14, n_paths=20, rng=np.random.default_rng(1))
    assert p.inflow.shape == (20, 14)
    for d in range(14):
        is_weekday = (h.dates[-1] + timedelta(days=d + 1)).weekday() < 5
        assert np.all(p.inflow[:, d] == (100.0 if is_weekday else 0.0))
    assert not p.low_confidence


def test_naive_skips_missing_and_flags_short_history():
    h = make_history(10)
    p = forecasters.get("seasonal_naive").forecast(h, horizon=7, n_paths=3, rng=np.random.default_rng(1))
    assert p.low_confidence

    h = make_history(70)
    h.missing[:] = True
    p = forecasters.get("seasonal_naive").forecast(h, horizon=7, n_paths=3, rng=np.random.default_rng(1))
    assert p.low_confidence and np.all(p.inflow == 0)

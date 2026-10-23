from datetime import date, timedelta

import numpy as np
import pytest

from zavozik_ml import forecasters
from zavozik_ml.forecasters import models  # noqa: F401
from zavozik_ml.forecasters.gbm import GBMGlobal, _nonneg


def company(days: int, seed: int, industry: str = "Общепит") -> forecasters.History:
    """Выручка по будням, зарплата 10-го и 25-го, ЕНП 28-го."""
    rng = np.random.default_rng(seed)
    start = date(2025, 1, 1)
    dates = [start + timedelta(days=i) for i in range(days)]
    wk = np.array([d.weekday() < 5 for d in dates])
    inflow = np.where(wk, rng.gamma(4, 25_000, days), 0.0)
    salary = np.array([60_000.0 if d.day in (10, 25) else 0.0 for d in dates])
    tax = np.array([40_000.0 if d.day == 28 else 0.0 for d in dates])
    other = np.where(wk, rng.gamma(2, 10_000, days), 0.0)
    return forecasters.History(
        dates=dates,
        inflow=inflow,
        outflow=salary + tax + other,
        missing=np.zeros(days, dtype=bool),
        industry=industry,
        categories={"salary": -salary, "tax": -tax},
    )


@pytest.fixture(scope="module")
def trained() -> GBMGlobal:
    m = GBMGlobal()
    m.fit([company(400, s) for s in range(6)])
    return m


def test_gbm_learns_calendar_payments(trained):
    h = company(300, 99)
    p = trained.forecast(h, 30, 300, np.random.default_rng(0))
    assert p.inflow.shape == (300, 30) and (p.inflow >= 0).all() and (p.outflow >= 0).all()
    _, mean_out, *_ = trained._components(h, 30)  # точечный прогноз оттока
    days = [h.dates[-1] + timedelta(days=i + 1) for i in range(30)]
    pay = [i for i, d in enumerate(days) if d.day in (10, 25, 28)]
    quiet = [i for i, d in enumerate(days) if d.weekday() >= 5 and d.day not in (10, 25, 28)]
    assert mean_out[pay].mean() > 3 * mean_out[quiet].mean()


def test_gbm_save_load_roundtrip(trained, tmp_path):
    trained.save(tmp_path / "gbm")
    m = GBMGlobal()
    assert m.load(tmp_path / "gbm") and m.ready and m.spread == trained.spread
    h = company(200, 5)
    a = trained.forecast(h, 14, 10, np.random.default_rng(1))
    b = m.forecast(h, 14, 10, np.random.default_rng(1))
    np.testing.assert_allclose(a.inflow, b.inflow)


def test_gbm_untrained_raises():
    with pytest.raises(forecasters.NotTrainedError):
        GBMGlobal().forecast(company(100, 1), 7, 3, np.random.default_rng(0))


def test_gbm_short_history_falls_back(trained):
    p = trained.forecast(company(70, 3), 30, 20, np.random.default_rng(0))
    assert p.low_confidence


def test_nonneg_preserves_net():
    i, o = np.array([-5.0, 3, -2]), np.array([3.0, -1, -3])
    a, b = _nonneg(i, o)
    assert (a >= 0).all() and (b >= 0).all()
    np.testing.assert_allclose(a - b, i - o)


def test_ets_shapes():
    p = forecasters.get("ets").forecast(company(120, 2), 14, 50, np.random.default_rng(0))
    assert p.inflow.shape == (50, 14) and (p.inflow >= 0).all()

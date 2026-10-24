"""Устойчивость к чужим данным: эксперты проверяют модель на своём наборе.

Модель должна выдавать конечные пути при наличии наблюдений и явный отказ
при полностью неизвестной истории: короткая история, пропуски, нет категорий и отрасли, незнакомая
отрасль, даты вне производственного календаря, длинный горизонт.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from zavozik_ml import calendar as cal
from zavozik_ml import forecasters
from zavozik_ml.forecasters import models  # noqa: F401
from zavozik_ml.forecasters.gbm import GBMGlobal

from .test_models import company


@pytest.fixture(scope="module")
def gbm() -> GBMGlobal:
    m = forecasters.get("gbm_global")  # экземпляр из реестра — его берёт ансамбль
    m.fit([company(400, s) for s in range(6)])
    return m


def bare(days: int, start: date = date(2025, 1, 1), missing_share: float = 0.0, seed: int = 0) -> forecasters.History:
    rng = np.random.default_rng(seed)
    dates = [start + timedelta(days=i) for i in range(days)]
    return forecasters.History(
        dates=dates,
        inflow=rng.gamma(2, 50_000, days),
        outflow=rng.gamma(2, 40_000, days),
        missing=rng.random(days) < missing_share,
    )


CASES = {
    "one_day": bare(1),
    "two_weeks": bare(14),
    "two_months": bare(60),
    "no_categories_no_industry": bare(300),
    "unknown_industry": company(300, 7, industry="Космический туризм"),
    "half_missing": bare(300, missing_share=0.5),
    "all_missing": bare(120, missing_share=1.0),
    "future_dates": bare(200, start=date(2041, 3, 1)),
    "past_dates": bare(200, start=date(1998, 6, 1)),
    "all_zero": forecasters.History(
        dates=[date(2025, 1, 1) + timedelta(days=i) for i in range(200)],
        inflow=np.zeros(200), outflow=np.zeros(200), missing=np.zeros(200, dtype=bool),
    ),
}


@pytest.mark.parametrize("model_name", ["seasonal_naive", "ets", "gbm_global", "ensemble"])
@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("horizon", [30, 90])
def test_models_return_valid_paths_or_reject_missing_evidence(gbm, model_name, case, horizon):
    h = CASES[case]
    if case == "all_missing":
        with pytest.raises(forecasters.InsufficientHistoryError):
            forecasters.get(model_name).forecast(h, horizon, 40, np.random.default_rng(0))
        return
    p = forecasters.get(model_name).forecast(h, horizon, 40, np.random.default_rng(0))
    assert p.inflow.shape == (40, horizon) and p.outflow.shape == (40, horizon)
    assert np.isfinite(p.inflow).all() and np.isfinite(p.outflow).all()
    assert (p.inflow >= 0).all() and (p.outflow >= 0).all()
    last = np.datetime64(h.dates[-1], "D")
    off = ~cal.forecast_day_mask(h, last + np.arange(1, horizon + 1))
    assert (p.inflow[:, off] == 0).all() and (p.outflow[:, off] == 0).all()


def test_short_history_is_low_confidence(gbm):
    for case in ("one_day", "two_weeks"):
        assert forecasters.get("ensemble").forecast(CASES[case], 30, 10, np.random.default_rng(0)).low_confidence


def test_calendar_outside_range_keeps_weekdays():
    d = np.array(["2041-03-02", "2041-03-04", "1998-06-06"], dtype="datetime64[D]")  # вс, вт, сб
    assert cal.is_workday(d).tolist() == [False, True, False]


def test_weekend_activity_is_not_silently_deleted():
    h = bare(100)
    h.inflow[:] = 100
    h.outflow[:] = 40
    assert not cal.uses_workday_calendar(h)
    p = forecasters.get('seasonal_naive').forecast(h, 14, 20, np.random.default_rng(1))
    np.testing.assert_allclose(p.inflow, 100)
    np.testing.assert_allclose(p.outflow, 40)


def test_calendar_policy_does_not_read_future():
    h = bare(100)
    h.inflow[:] = 0
    h.outflow[:] = 0
    h.inflow[-1] = 100  # 10 April 2025 Thursday: find a weekend instead
    h.inflow[-1] = 0
    i = next(i for i in range(80,100) if not cal.is_workday([h.dates[i]])[0])
    h.inflow[i] = 100
    assert cal.uses_workday_calendar(h.head(i))
    assert not cal.uses_workday_calendar(h.head(i+1))


def test_auto_routes_outside_training_support_to_local_model(gbm):
    from zavozik_ml.forecasters.base import select_model
    h = bare(200)  # all calendar days active, unlike the training source
    assert select_model('auto', h).name == 'seasonal_naive'
    assert select_model('gbm_global', h).name == 'gbm_global'  # explicit selection remains explicit
    only_out = forecasters.History(h.dates, np.zeros(200), h.outflow, h.missing)
    assert select_model('auto', only_out).name == 'seasonal_naive'

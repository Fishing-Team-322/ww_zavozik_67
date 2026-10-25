"""ETS (Holt-Winters) с недельной сезонностью — классический статистический
бейзлайн, отдельная модель на каждую компанию и направление потока.

Пропуски выписки заполняются средним по дню недели; пути — симуляция из
модели с аддитивной ошибкой, обрезанная снизу нулём.
"""

from __future__ import annotations

import warnings

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from zavozik_ml import calendar as cal

from .base import Forecaster, History, Paths, register
from .naive import MIN_CONFIDENT_DAYS, SeasonalNaive

WINDOW = 182  # дней истории для подгонки


def _fill_missing(y: np.ndarray, missing: np.ndarray, weekdays: np.ndarray) -> np.ndarray:
    y = y.copy()
    for wd in range(7):
        sel = weekdays == wd
        ok = sel & ~missing
        y[sel & missing] = y[ok].mean() if ok.any() else 0.0
    return y


@register
class ETS(Forecaster):
    name = "ets"
    description = "Holt-Winters с недельной сезонностью, отдельно на компанию"

    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths:
        if history.valid_days < 3 * 7:
            return SeasonalNaive().forecast(history, horizon, n_paths, rng)
        tail = slice(max(0, len(history) - WINDOW), len(history))
        missing = history.missing[tail]
        weekdays = np.array([d.weekday() for d in history.dates[tail]])
        out = []
        for series in (history.inflow[tail], history.outflow[tail]):
            y = _fill_missing(series, missing, weekdays)
            out.append(self._simulate(y, horizon, n_paths, rng))
        work = cal.forecast_day_mask(history, np.datetime64(history.dates[-1], "D") + np.arange(1, horizon + 1))
        return Paths(out[0] * work, out[1] * work, low_confidence=history.valid_days < MIN_CONFIDENT_DAYS)

    @staticmethod
    def _simulate(y: np.ndarray, horizon: int, n_paths: int, rng: np.random.Generator) -> np.ndarray:
        if np.allclose(y, 0):
            return np.zeros((n_paths, horizon))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(y, seasonal="add", seasonal_periods=7, initialization_method="estimated").fit()
            # statsmodels accepts only None, an int or a RandomState; numpy scalars
            # (e.g. numpy.int64) are rejected by current releases.
            sims = fit.simulate(horizon, repetitions=n_paths, error="add",
                                random_state=int(rng.integers(2**31)))
        return np.clip(np.asarray(sims).T.reshape(n_paths, horizon), 0, None)

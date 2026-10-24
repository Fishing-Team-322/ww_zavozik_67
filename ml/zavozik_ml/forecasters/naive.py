"""Сезонный naive-бутстрап — бейзлайн, с которым сравниваем все модели.

Для каждого рабочего дня горизонта берём случайный рабочий день с тем же днём
недели из последних `weeks` недель истории (без пропусков); в нерабочий день
по производственному календарю — ноль. Встроенный фолбэк в Go
(backend/internal/forecast/naive.go) — тот же алгоритм без календаря.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from zavozik_ml import calendar as cal

from .base import Forecaster, History, InsufficientHistoryError, Paths, register

MIN_CONFIDENT_DAYS = 28


@register
class SeasonalNaive(Forecaster):
    name = "seasonal_naive"
    description = "Бейзлайн: бутстрап по дню недели за последние 8 недель"
    weeks = 8

    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths:
        inflow = np.zeros((n_paths, horizon))
        outflow = np.zeros((n_paths, horizon))
        if not history.dates:
            raise InsufficientHistoryError("history contains no observed days")

        start = max(0, len(history.dates) - self.weeks * 7)
        # Пулы по дню недели только из рабочих дней (по производственному
        # календарю); в нерабочий день прогноз — ноль, рабочая суббота берёт
        # любой рабочий день.
        calendar_only = cal.uses_workday_calendar(history)
        work_hist = cal.forecast_day_mask(history, np.array(history.dates[start:], dtype="datetime64[D]"))
        pools: dict[int, list[int]] = {wd: [] for wd in range(7)}
        for j, i in enumerate(range(start, len(history.dates))):
            if not history.missing[i] and work_hist[j]:
                pools[history.dates[i].weekday()].append(i)
        any_work = [i for wd in range(7) for i in pools[wd]]
        valid = sum(len(p) for p in pools.values())
        if not any_work:
            raise InsufficientHistoryError("no observed eligible days in the seasonal sampling window")

        last = history.dates[-1]
        targets = [last + timedelta(days=d + 1) for d in range(horizon)]
        work_target = cal.forecast_day_mask(history, np.array(targets, dtype="datetime64[D]"))
        for d, day in enumerate(targets):
            if not work_target[d]:
                continue
            pool = pools[day.weekday()] if not calendar_only or day.weekday() < 5 else any_work
            pool = pool or any_work
            if not pool:
                continue
            idx = rng.choice(pool, size=n_paths)
            inflow[:, d] = history.inflow[idx]
            outflow[:, d] = history.outflow[idx]
        return Paths(inflow, outflow, low_confidence=valid < MIN_CONFIDENT_DAYS)

"""Сезонный naive-бутстрап — бейзлайн, с которым сравниваем все модели.

Для каждого дня горизонта берём случайный день с тем же днём недели из
последних `weeks` недель истории (без пропусков). Тот же алгоритм, что
встроенный фолбэк в Go (backend/internal/forecast/naive.go).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from .base import Forecaster, History, Paths, register

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
            return Paths(inflow, outflow, low_confidence=True)

        start = max(0, len(history.dates) - self.weeks * 7)
        pools: dict[int, list[int]] = {wd: [] for wd in range(7)}
        for i in range(start, len(history.dates)):
            if not history.missing[i]:
                pools[history.dates[i].weekday()].append(i)
        valid = sum(len(p) for p in pools.values())

        last = history.dates[-1]
        for d in range(horizon):
            pool = pools[(last + timedelta(days=d + 1)).weekday()]
            if not pool:
                continue
            idx = rng.choice(pool, size=n_paths)
            inflow[:, d] = history.inflow[idx]
            outflow[:, d] = history.outflow[idx]
        return Paths(inflow, outflow, low_confidence=valid < MIN_CONFIDENT_DAYS)

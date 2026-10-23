"""Ансамбль: смесь путей глобального бустинга и сезонного naive.

Половина путей от каждой модели. Бустинг даёт уровень и календарь
(зарплата, ЕНП), naive — реалистичные «тяжёлые» дни из истории компании;
смесь устойчивее на компаниях, которых бустинг не видел.
"""

from __future__ import annotations

import numpy as np

from .base import Forecaster, History, Paths, get, register


@register
class Ensemble(Forecaster):
    name = "ensemble"
    description = "Смесь путей LightGBM и seasonal naive (50/50)"
    members = ("gbm_global", "seasonal_naive")

    @property
    def ready(self) -> bool:
        return all(get(m).ready for m in self.members)

    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths:
        sizes = [n_paths // 2, n_paths - n_paths // 2]
        parts = [get(m).forecast(history, horizon, k, rng) for m, k in zip(self.members, sizes)]
        return Paths(
            np.concatenate([p.inflow for p in parts]),
            np.concatenate([p.outflow for p in parts]),
            low_confidence=any(p.low_confidence for p in parts),
        )

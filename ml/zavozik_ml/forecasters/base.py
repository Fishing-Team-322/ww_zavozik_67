"""Интерфейс прогнозной модели и реестр.

Новая модель = класс-наследник Forecaster + декоратор @register:

    @register
    class Chronos(Forecaster):
        name = "chronos"
        description = "Amazon Chronos, zero-shot"
        def forecast(self, history, horizon, n_paths, rng): ...

После этого модель доступна через gRPC ListModels/Forecast, в бэктесте
(`cmd/backtest -model chronos`) и на странице «Как мы считаем».
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import numpy as np


@dataclass(frozen=True)
class History:
    """Дневные потоки стохастической части, каждый календарный день подряд."""

    dates: list[date]
    inflow: np.ndarray  # shape (n,), >= 0
    outflow: np.ndarray  # shape (n,), >= 0
    missing: np.ndarray  # shape (n,), bool — день в пропуске выписки
    industry: str = ""

    @property
    def valid_days(self) -> int:
        return int((~self.missing).sum())


@dataclass(frozen=True)
class Paths:
    """Траектории на horizon дней вперёд: inflow[path, day]."""

    inflow: np.ndarray  # shape (n_paths, horizon)
    outflow: np.ndarray  # shape (n_paths, horizon)
    low_confidence: bool = False


class Forecaster(ABC):
    name: str
    description: str

    @abstractmethod
    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths: ...


_REGISTRY: dict[str, Forecaster] = {}
DEFAULT_MODEL = "seasonal_naive"


def register(cls: type[Forecaster]) -> type[Forecaster]:
    if cls.name in _REGISTRY:
        raise ValueError(f"model {cls.name!r} already registered")
    _REGISTRY[cls.name] = cls()
    return cls


def get(name: str) -> Forecaster:
    if name in ("", "auto"):
        name = DEFAULT_MODEL
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown model {name!r}; available: {sorted(_REGISTRY)}") from None


def all_models() -> list[Forecaster]:
    return [_REGISTRY[n] for n in sorted(_REGISTRY)]

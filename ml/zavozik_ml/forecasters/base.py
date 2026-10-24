"""Интерфейс прогнозной модели и реестр.

Новая модель = класс-наследник Forecaster + декоратор @register:

    @register
    class Chronos(Forecaster):
        name = "chronos"
        description = "Amazon Chronos, zero-shot"
        def forecast(self, history, horizon, n_paths, rng): ...

После этого модель доступна через gRPC ListModels/Forecast, в бэктесте
(`python -m zavozik_ml.eval.backtest --models chronos`) и на странице
«Как мы считаем». Глобальные модели (одна на все компании) переопределяют
fit/save/load; артефакты лежат в ml/artifacts/<name>/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

# Внутренние движения владельца: не выручка и не расход бизнеса.
INTERNAL_CATEGORIES = ("own_transfer", "owner_loan")
# Регулярные обязательные платежи — главный календарный сигнал.
REGULAR_OUT_CATEGORIES = ("salary", "tax", "rent", "utilities", "loan_payment", "leasing", "bank_fee")


@dataclass(frozen=True)
class History:
    """Дневные потоки компании, каждый календарный день подряд."""

    dates: list[date]
    inflow: np.ndarray  # shape (n,), >= 0, без внутренних переводов
    outflow: np.ndarray  # shape (n,), >= 0, без внутренних переводов
    missing: np.ndarray  # shape (n,), bool — день в пропуске выписки
    industry: str = ""
    # Сумма за день по категории со знаком (+ приход, − расход); может быть пустым.
    categories: dict[str, np.ndarray] = field(default_factory=dict)
    # Когда нарушение сверки стало известно. Маска истории на дату прогноза
    # не должна зависеть от более поздней банковской выписки.
    missing_known_on: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.dates)

    @property
    def valid_days(self) -> int:
        return int((~self.missing).sum())

    def category(self, name: str) -> np.ndarray:
        return self.categories.get(name, np.zeros(len(self.dates)))

    def regular_outflow(self) -> np.ndarray:
        """Регулярные обязательные списания за день (>= 0)."""
        total = np.zeros(len(self.dates))
        for c in REGULAR_OUT_CATEGORIES:
            total -= np.minimum(self.category(c), 0)
        return total

    def head(self, n: int) -> History:
        """Первые n дней — история на момент n-1."""
        n = max(0, min(n, len(self)))
        missing = self.missing[:n].copy()
        known = self.missing_known_on[:n] if self.missing_known_on is not None else None
        if n and known is not None:
            missing &= np.isnat(known) | (known <= np.datetime64(self.dates[n - 1]))
        return History(
            dates=self.dates[:n],
            inflow=self.inflow[:n],
            outflow=self.outflow[:n],
            missing=missing,
            industry=self.industry,
            categories={k: v[:n] for k, v in self.categories.items()},
            missing_known_on=known,
        )


@dataclass(frozen=True)
class Paths:
    """Траектории на horizon дней вперёд: inflow[path, day]."""

    inflow: np.ndarray  # shape (n_paths, horizon)
    outflow: np.ndarray  # shape (n_paths, horizon)
    low_confidence: bool = False


class NotTrainedError(RuntimeError):
    pass


class Forecaster(ABC):
    name: str
    description: str
    # Глобальная модель: учится на всех компаниях, требует fit или load.
    is_global: bool = False

    @abstractmethod
    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths: ...

    def fit(self, histories: list[History]) -> None:  # noqa: B027 — по умолчанию модели без обучения
        pass

    def save(self, directory: Path) -> None:  # noqa: B027
        pass

    def load(self, directory: Path) -> bool:
        """Загрузить артефакт; False — артефакта нет."""
        return True

    @property
    def ready(self) -> bool:
        return True


_REGISTRY: dict[str, Forecaster] = {}
# Что выбирается при model="auto": лучшая обученная модель по бэктесту.
AUTO_PREFERENCE = ("ensemble", "gbm_global", "seasonal_naive")


def register(cls: type[Forecaster]) -> type[Forecaster]:
    if cls.name in _REGISTRY:
        raise ValueError(f"model {cls.name!r} already registered")
    _REGISTRY[cls.name] = cls()
    return cls


def default_model() -> str:
    for name in AUTO_PREFERENCE:
        m = _REGISTRY.get(name)
        if m is not None and m.ready:
            return name
    return "seasonal_naive"


def get(name: str) -> Forecaster:
    if name in ("", "auto"):
        name = default_model()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown model {name!r}; available: {sorted(_REGISTRY)}") from None


def domain_warnings(history: History) -> list[str]:
    """Observable support checks, without looking at future targets."""
    from zavozik_ml.calendar import uses_workday_calendar
    warnings = []
    if not uses_workday_calendar(history):
        warnings.append("nonworkday_activity_detected")
    valid = ~history.missing
    if valid.any() and (not (history.inflow[valid] > 0).any() or not (history.outflow[valid] > 0).any()):
        warnings.append("single_channel_history")
    return warnings


def select_model(name: str, history: History) -> Forecaster:
    """Auto abstains from cross-company transfer outside observed training support."""
    if name in ("", "auto") and domain_warnings(history):
        return get("seasonal_naive")
    return get(name)


def all_models() -> list[Forecaster]:
    return [_REGISTRY[n] for n in sorted(_REGISTRY)]

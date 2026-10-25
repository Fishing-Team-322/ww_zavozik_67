"""Serving adapters for the event generators (`event_blocks`, `event_hybrid`).

The serving contract (`Forecaster.forecast`) exchanges daily inflow/outflow, while
the event models need transactions. `History` currently carries no transaction
list, so this adapter synthesises one event per non-zero direction-day at that
day's total. That keeps flows exact and is honest about what it loses: intra-day
detail, per-transaction amounts and counterparties. When `History` gains
transactions (the proto already has `HistoryTransaction transactions = 9` but the
server does not forward them), only `history_to_events` needs to change.

Both models are 30-day models. Longer horizons are sampled in independent chunks
from the same origin, which is why `low_confidence` is set above 30 days.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from zavozik_ml.event_forecasters.blocks import Model as BlocksModel
from zavozik_ml.event_forecasters.core import EventHistory, EventPaths, FitOptions
from zavozik_ml.event_forecasters.hybrid import Model as HybridModel

from .base import Forecaster, History, Paths, register

MIN_CONFIDENT_DAYS = 28
MAX_MISSING_SHARE = 0.2
NATIVE_HORIZON = 30
EVENT_COLUMNS = ["date", "direction", "amount", "category", "counterparty"]


def history_to_events(history: History, company_id: str = "serving") -> EventHistory:
    """Adapt a daily `History` to `EventHistory` by one event per non-zero direction-day."""
    if not history.dates:
        raise ValueError("event models need a non-empty history")
    dates = np.asarray(history.dates, dtype="datetime64[D]")
    missing = np.asarray(history.missing, dtype=bool)
    if len(missing) != len(dates):
        raise ValueError("history masks do not match the dates")
    detected = np.full(len(dates), np.datetime64("NaT", "D"))
    detected[missing] = dates[missing]  # a gap is unknown, not a silent day
    inflow = np.asarray(history.inflow, dtype=float)
    outflow = np.asarray(history.outflow, dtype=float)
    if not np.isfinite(inflow).all() or not np.isfinite(outflow).all():
        raise ValueError("history flows must be finite")
    rows = []
    for offset in np.flatnonzero(~missing):
        stamp = pd.Timestamp(dates[offset])
        if inflow[offset] > 0:
            rows.append(dict(date=stamp, direction=0, amount=float(inflow[offset]),
                             category="unobserved", counterparty=""))
        if outflow[offset] > 0:
            rows.append(dict(date=stamp, direction=1, amount=float(outflow[offset]),
                             category="unobserved", counterparty=""))
    frame = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    return EventHistory(company_id, history.industry or "", dates, missing.copy(),
                        detected, frame)


def events_to_paths(events: EventPaths, n_paths: int, horizon: int) -> Paths:
    """Turn retained events back into the serving path arrays."""
    amounts, _ = events.daily()
    if amounts.shape[0] != n_paths or amounts.shape[1] != horizon:
        raise ValueError(f"event paths have shape {amounts.shape}, expected {(n_paths, horizon, 2)}")
    inflow, outflow = amounts[:, :, 0], amounts[:, :, 1]
    if not np.isfinite(amounts).all() or (amounts < 0).any():
        raise ValueError("event paths must be finite and non-negative")
    return Paths(inflow, outflow)


class _EventForecaster(Forecaster):
    """Shared adapt/chunk/low-confidence logic; subclasses supply the model class."""

    model_class = None
    fit_options = FitOptions

    def __init__(self) -> None:
        # Priors from an explicit fit(). Never cache a model fitted on one request:
        # the registry stores a shared singleton, so that would leak one company's
        # history into the next request (and into concurrent ones).
        self._prior = None

    @property
    def ready(self) -> bool:
        # No trained artefact is required: local donors and empirical priors suffice.
        return True

    def fit(self, histories: list[History]) -> None:
        adapted = [history_to_events(h) for h in histories if len(h.dates)]
        model = self.model_class(self.fit_options())
        model.fit(adapted)
        self._prior = model

    def _fitted(self, history: History):
        """Global priors if the model was explicitly fitted, else a per-request fit.

        A per-request model keeps requests independent: identical history and seed
        always give identical output regardless of what was forecast before.
        """
        if self._prior is not None:
            return self._prior
        model = self.model_class(self.fit_options())
        model.fit([history_to_events(history)])
        return model

    def forecast(self, history: History, horizon: int, n_paths: int,
                 rng: np.random.Generator) -> Paths:
        horizon, n_paths = int(horizon), int(n_paths)
        if horizon < 1 or n_paths < 1:
            raise ValueError("horizon and n_paths must be positive")
        model = self._fitted(history)
        events = history_to_events(history)
        if not len(events.events):  # observed silence: no donors, no invented activity
            zeros = np.zeros((n_paths, horizon))
            return Paths(zeros, zeros.copy(), low_confidence=True)
        chunks = int(np.ceil(horizon / NATIVE_HORIZON))
        parts = []
        for _ in range(chunks):
            paths = model.sample(events, NATIVE_HORIZON, n_paths, rng)
            parts.append(events_to_paths(paths, n_paths, NATIVE_HORIZON))
        inflow = np.concatenate([p.inflow for p in parts], axis=1)[:, :horizon]
        outflow = np.concatenate([p.outflow for p in parts], axis=1)[:, :horizon]
        missing = np.asarray(history.missing, dtype=bool)
        low = (chunks > 1 or int((~missing).sum()) < MIN_CONFIDENT_DAYS
               or (missing.mean() > MAX_MISSING_SHARE if len(missing) else True))
        return Paths(inflow, outflow, low_confidence=bool(low))


@register
class EventBlocks(_EventForecaster):
    name = "event_blocks"
    description = "Whole-event donor resampling with level correction and month-phase donors"
    model_class = BlocksModel


@register
class EventHybrid(_EventForecaster):
    name = "event_hybrid"
    description = "Recurring schedules plus disjoint residual event bootstrap"
    model_class = HybridModel

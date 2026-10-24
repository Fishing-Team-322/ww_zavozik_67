"""Shared, day-resolution event contract for CPU benchmark implementations.

Only canonical business transactions are supplied. All timestamps are days;
row order within a day has no economic meaning. Missing days are not zeros.
Generators return complete, equally weighted scenarios, not marginal quantiles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

import numpy as np
import pandas as pd

from zavozik_ml import calendar as cal

EVENT_COLUMNS = ["path", "day", "direction", "amount", "category", "counterparty", "known_event_id"]


@dataclass(frozen=True)
class FitOptions:
    seed: int = 20261024
    threads: int = 8
    rounds: int = 120
    epochs: int = 8
    max_training_rows: int = 100_000
    hidden_size: int = 32
    max_events_per_day: int = 128
    device: str = "cpu"


@dataclass(frozen=True)
class EventHistory:
    company_id: str
    industry: str
    dates: np.ndarray
    missing: np.ndarray
    detected: np.ndarray
    raw_events: pd.DataFrame  # date, direction(0=in/1=out), amount, category, counterparty

    def __post_init__(self):
        dates = np.asarray(self.dates, dtype="datetime64[D]")
        if not len(dates) or not (np.diff(dates) == np.timedelta64(1, "D")).all():
            raise ValueError("event history needs continuous, nonempty daily dates")
        if len(self.missing) != len(dates) or len(self.detected) != len(dates):
            raise ValueError("history masks do not match dates")
        if np.isnat(np.asarray(self.detected)[self.missing]).any():
            raise ValueError("missing history needs discovery dates")
        if len(self.raw_events):
            d = self.raw_events.date.to_numpy(dtype="datetime64[D]")
            if (d < dates[0]).any() or (d > dates[-1]).any():
                raise ValueError("raw events must be bounded by history dates")
            if not self.raw_events.direction.isin([0, 1]).all():
                raise ValueError("invalid historical direction")
            if not np.isfinite(self.raw_events.amount).all() or (self.raw_events.amount < 0).any():
                raise ValueError("historical amounts must be finite and nonnegative")

    @property
    def as_of(self):
        return np.asarray(self.dates, dtype="datetime64[D]")[-1]

    @cached_property
    def known(self):
        return ~(self.missing & (self.detected <= self.as_of))

    @cached_property
    def events(self):
        """Complete observed days as known AT THIS cutoff; never raw future gaps."""
        good = np.asarray(self.dates, dtype="datetime64[D]")[self.known]
        return self.raw_events[self.raw_events.date.isin(pd.to_datetime(good))].copy()

    def prefix(self, cutoff):
        n = int(np.searchsorted(self.dates, np.datetime64(cutoff, "D"), side="right"))
        if n == 0:
            raise ValueError("cutoff precedes company history")
        return EventHistory(self.company_id, self.industry, self.dates[:n].copy(),
                            self.missing[:n].copy(), self.detected[:n].copy(),
                            self.raw_events[self.raw_events.date <= pd.Timestamp(self.dates[n - 1])].copy())

    @cached_property
    def daily_counts(self):
        result = np.zeros((len(self.dates), 2), dtype=np.float64)
        ev = self.events
        if len(ev):
            day = (ev.date.to_numpy(dtype="datetime64[D]") - self.dates[0]).astype(int)
            np.add.at(result, (day, ev.direction.to_numpy(int)), 1.)
        result[~self.known] = np.nan
        return result

    @cached_property
    def daily_amounts(self):
        result = np.zeros((len(self.dates), 2), dtype=np.float64)
        ev = self.events
        if len(ev):
            day = (ev.date.to_numpy(dtype="datetime64[D]") - self.dates[0]).astype(int)
            np.add.at(result, (day, ev.direction.to_numpy(int)), ev.amount.to_numpy(float))
        result[~self.known] = np.nan
        return result

    def allowed(self, dates):
        # An observed event, even amount zero, establishes nonworking-day support.
        calendar_only = not (len(self.events) and (~cal.is_workday(self.events.date.to_numpy())).any())
        return cal.is_workday(dates) if calendar_only else np.ones(len(dates), dtype=bool)

    def amount_scale(self, direction):
        values = self.events.loc[(self.events.direction == direction) & (self.events.amount > 0), "amount"].to_numpy()
        return float(np.median(values)) if len(values) else 1.


@dataclass
class EventPaths:
    origin: np.datetime64
    horizon: int
    n_paths: int
    events: pd.DataFrame
    diagnostics: dict = field(default_factory=dict)

    @classmethod
    def from_records(cls, history, horizon, n_paths, records, diagnostics=None):
        frame = pd.DataFrame.from_records(records)
        for key in EVENT_COLUMNS:
            if key not in frame:
                frame[key] = "" if key in ("counterparty", "known_event_id") else pd.Series(dtype="object")
        return cls(history.as_of, horizon, n_paths, frame[EVENT_COLUMNS], diagnostics or {}).validate()

    def validate(self):
        if self.horizon < 1 or self.n_paths < 1:
            raise ValueError("positive horizon and path count required")
        if not set(EVENT_COLUMNS) <= set(self.events):
            raise ValueError("missing generated event columns")
        e = self.events
        if len(e):
            for key in ("path", "day", "direction"):
                values = pd.to_numeric(e[key]).to_numpy(float)
                if not np.isfinite(values).all() or not (values == np.floor(values)).all():
                    raise ValueError("generated event indices must be finite integers")
            if not e.path.between(0, self.n_paths - 1).all() or not e.day.between(1, self.horizon).all():
                raise ValueError("event outside scenario or horizon")
            if not e.direction.isin([0, 1]).all():
                raise ValueError("invalid generated direction")
            if not np.isfinite(e.amount.to_numpy(float)).all() or (e.amount < 0).any():
                raise ValueError("generated amounts must be finite and nonnegative")
            if e.category.isna().any() or (e.category.astype(str).str.len() == 0).any():
                raise ValueError("generated events require a mark, including explicit unknown")
            linked = e[e.known_event_id.astype(str) != ""]
            if linked.duplicated(["path", "known_event_id"]).any():
                raise ValueError("known event emitted more than once in a scenario")
        return self

    def daily(self):
        """Return (amounts, counts), both shaped [scenario, day, direction]."""
        self.validate()
        amounts = np.zeros((self.n_paths, self.horizon, 2))
        counts = np.zeros_like(amounts)
        e = self.events
        if len(e):
            idx = (e.path.to_numpy(int), e.day.to_numpy(int) - 1, e.direction.to_numpy(int))
            np.add.at(amounts, idx, e.amount.to_numpy(float))
            np.add.at(counts, idx, 1.)
        return amounts, counts

    def dated_events(self):
        result = self.events.copy()
        result["date"] = pd.to_datetime(np.datetime64(self.origin, "D") + result.day.to_numpy(int).astype("timedelta64[D]"))
        return result


def calendar_features(dates):
    dates = np.asarray(dates, dtype="datetime64[D]")
    days = pd.DatetimeIndex(dates)
    f = dict(weekday=days.dayofweek, day=days.day, month=days.month,
             days_to_eom=days.days_in_month - days.day)
    f.update(cal.features(dates, dates))
    return pd.DataFrame(f, dtype=np.float32)


class ConditionalAmounts:
    """Shallow empirical mark/industry pooling with company-relative sizes.

    Fit pools use only supplied prefixes. Local donors use only complete days
    visible at sample time. No invented counterparty identities are generated.
    """
    def fit(self, histories):
        pools = {}
        for h in histories:
            for (direction, category), group in h.events.groupby(["direction", "category"]):
                normalized = group.amount.to_numpy(float) / h.amount_scale(direction)
                for key in ((h.industry, int(direction), str(category)), ("*", int(direction), str(category)), ("*", int(direction), "*")):
                    pools.setdefault(key, []).extend(normalized.tolist())
        self.pools = {key: np.asarray(values) for key, values in pools.items()}
        return self

    def sample(self, history, direction, category, n, rng):
        if n == 0:
            return np.empty(0)
        local = history.events
        local = local[(local.direction == direction) & (local.category == category) &
                      (local.date >= pd.Timestamp(history.as_of - np.timedelta64(181, "D")))]
        if len(local) >= 3:
            return rng.choice(local.amount.to_numpy(float), n)
        for key in ((history.industry, direction, category), ("*", direction, category), ("*", direction, "*")):
            pool = self.pools.get(key)
            if pool is not None and len(pool):
                return rng.choice(pool, n) * history.amount_scale(direction)
        return np.zeros(n)


def available_marks(histories):
    marks = sorted({str(mark) for h in histories for mark in h.events.category.unique()})
    return marks or ["unknown"]

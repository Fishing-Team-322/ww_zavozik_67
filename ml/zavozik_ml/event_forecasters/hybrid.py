"""Standalone recurring-schedule + disjoint residual event generator (research only).

Two disjoint sources produce every scenario:

* recurring schedules detected from the complete observed days of the sampled
  history (stable counterparty/direction/category cadence, or a conservative
  direction/category fallback when the hashed counterparty is empty);
* a residual stream built from the history rows that no detected schedule
  explains, re-timed with a whole-week event bootstrap (or a small workday
  count model when no complete donor week exists).

Every generated event is retained individually; scenarios are equally weighted
and no per-event probability is attached. Detected schedules are not known
invoice obligations: no ``known_event_id`` is ever emitted, so real invoice
lateness cannot be learned from this case data.

Missing days are censoring, not zeros: a schedule is only due in periods whose
anchor day is observed, and the residual bootstrap only re-uses complete weeks.
``FitOptions.max_events_per_day`` caps a scenario day; every removed event is
counted in ``EventPaths.diagnostics["clipped_events"]``. ``rounds``, ``epochs``,
``hidden_size`` and ``threads`` are unused (no learned network / count model);
``seed`` is honoured by the caller-built ``rng`` of :meth:`Model.sample`.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from zavozik_ml.event_forecasters.core import (
    ConditionalAmounts,
    EventPaths,
    FitOptions,
    calendar_features,
)

_CALENDAR_ANCHORS = (
    ("first_workday", "wd_of_month", 1),
    ("last_workday", "wd_to_eom", 0),
    ("tax_day", "is_tax_day", 1),
    ("pay10", "is_pay10", 1),
    ("pay25", "is_pay25", 1),
)
_KIND_PRIORITY = {"calendar": 3, "monthly_dom": 2, "weekly": 1}
_MIN_OCCURRENCES = 3
_FALLBACK_OCCURRENCES = 2  # extra support demanded without a counterparty key
_MIN_STABILITY = 0.60
_DAY_OF_MONTH_TOLERANCE = 2
_SNAP_DAYS = 3
_PRIOR_STRENGTH = 2.0
_DEFAULT_OCCURRENCE = 0.85
_MAX_POOL = 2000
_MIN_LOCAL_AMOUNTS = 5
_MIN_LOCAL_RATE_ROWS = 8


def _to_int(dates):
    return np.asarray(dates, dtype="datetime64[D]").astype(np.int64)


def _from_int(days):
    return np.asarray(days, dtype=np.int64).astype("datetime64[D]")


def _weekday(days):
    return pd.DatetimeIndex(_from_int(days)).dayofweek.to_numpy().astype(np.int64)


def _day_of_month(days):
    return pd.DatetimeIndex(_from_int(days)).day.to_numpy().astype(np.int64)


def _week_starts(days):
    days = np.asarray(days, dtype=np.int64)
    return days - _weekday(days)


def _month_index(days):
    return _from_int(days).astype("datetime64[M]").astype(np.int64)


def _month_first_day(months):
    return np.asarray(months, dtype=np.int64).astype("datetime64[M]").astype("datetime64[D]").astype(np.int64)


def _month_day(months, day_of_month):
    """Calendar day in each month, clamped to that month's length."""
    months = np.asarray(months, dtype=np.int64)
    length = _month_first_day(months + 1) - _month_first_day(months)
    return _month_first_day(months) + np.minimum(int(day_of_month), length) - 1


def _anchor_days(days, column, value):
    """First observed day per month carrying a calendar anchor flag."""
    if not len(days):
        return {}
    days = np.sort(np.unique(np.asarray(days, dtype=np.int64)))
    features = calendar_features(_from_int(days))
    hit = (features[column].to_numpy() == value) & (features["is_workday"].to_numpy() == 1)
    table = {}
    for month, day in zip(_month_index(days[hit]).tolist(), days[hit].tolist()):
        table.setdefault(int(month), int(day))
    return table


def _due(periods, expected):
    """Periods the schedule was due while observable, plus periods it paid but could not be checked."""
    seen = {int(p) for p in periods}
    known = {int(p) for p in expected}
    return len(known) + len(seen - known)


@dataclass(eq=False)
class _Stream:
    counterparty: str
    direction: int
    category: str
    kind: str
    anchor: object
    shifts: np.ndarray
    amounts: np.ndarray
    occurrences: int
    due: int
    days: np.ndarray
    periods: np.ndarray  # observed schedule occurrences, not generated-event IDs

    @property
    def key(self):
        return (self.counterparty, int(self.direction), self.category, self.kind)

    @property
    def p_occur(self):
        return float(self.occurrences) / float(max(self.due, self.occurrences))


def _stream_candidates(days, window, anchors):
    """Supported schedules for one sorted group of distinct upcoming-known event days."""
    window = np.asarray(window, dtype=np.int64)
    observed = set(window.tolist())
    as_of = int(window[-1])
    gaps = np.diff(days)
    weekday = _weekday(days)
    dom = _day_of_month(days)
    months = _month_index(days)
    as_of_month = int(_month_index(np.array([as_of], dtype=np.int64))[0])
    out = []

    if len(gaps) >= 2:
        gap_share = float(((gaps >= 5) & (gaps <= 9)).mean())
        anchor = int(np.bincount(weekday, minlength=7).argmax())
        weekday_share = float((weekday == anchor).mean())
        if gap_share >= _MIN_STABILITY and weekday_share >= _MIN_STABILITY:
            starts = _week_starts(days)
            last_week = int(_week_starts(np.array([as_of], dtype=np.int64))[0])
            weeks = np.arange(int(starts[0]), last_week + 1, 7, dtype=np.int64)
            out.append(dict(
                kind="weekly", anchor=anchor, periods=starts, supported_days=days,
                shifts=days - (starts + anchor),
                expected=[int(w) for w in weeks if int(w) + anchor in observed],
                score=min(gap_share, weekday_share)))

    dom_anchor = int(np.median(dom))
    dom_share = float((np.abs(dom - dom_anchor) <= _DAY_OF_MONTH_TOLERANCE).mean())
    span = np.arange(int(months[0]), as_of_month + 1, dtype=np.int64)
    # One scheduled occurrence per month: a skipped month is a censored spell, not a long
    # observed silence, so no inter-arrival test is applied here.
    monthly = len(months) / len(np.unique(months)) <= 1.5 and len(months) / len(span) >= 0.5
    if dom_share >= _MIN_STABILITY and monthly:
        anchor_day = dict(zip(span.tolist(), _month_day(span, dom_anchor).tolist()))
        matched = np.abs(dom - dom_anchor) <= _DAY_OF_MONTH_TOLERANCE
        out.append(dict(
            kind="monthly_dom", anchor=dom_anchor, periods=months[matched], supported_days=days[matched],
            shifts=days[matched] - np.array([anchor_day[int(m)] for m in months[matched]], dtype=np.int64),
            expected=[int(m) for m, day in anchor_day.items() if day in observed],
            score=dom_share))

    for name, column, value in _CALENDAR_ANCHORS:
        table = anchors[name]
        matched = np.array([int(m) in table and table[int(m)] == int(d) for m, d in zip(months, days)])
        share = float(matched.mean())
        if share < _MIN_STABILITY:
            continue
        periods = months[matched]
        out.append(dict(
            kind="calendar", anchor=name, periods=periods, supported_days=days[matched],
            shifts=days[matched] - np.array([table[int(m)] for m in periods], dtype=np.int64),
            expected=[m for m in table if int(periods[0]) <= m <= as_of_month],
            score=share))
    return out


def _group_stream(counterparty, direction, category, days, amounts, window, anchors, min_occ):
    unique = np.unique(days)
    if len(unique) < min_occ:
        return None
    candidates = [c for c in _stream_candidates(unique, window, anchors)
                  if len(c["supported_days"]) >= min_occ]
    if not candidates:
        return None
    best = max(candidates, key=lambda c: (round(c["score"], 6), _KIND_PRIORITY[c["kind"]]))
    supported = np.asarray(best["supported_days"], dtype=np.int64)
    return _Stream(counterparty, int(direction), category, best["kind"], best["anchor"],
                   np.asarray(best["shifts"], dtype=np.int64), np.asarray(amounts, dtype=float)[np.isin(days, supported)],
                   int(len(np.unique(best["periods"]))), int(_due(best["periods"], best["expected"])),
                   supported, np.unique(best["periods"]))


def _detect_streams(events, window_days):
    """Detected schedules; ``window_days`` are the days observed at this cutoff."""
    if not len(events) or not len(window_days):
        return []
    window = np.sort(np.unique(_to_int(window_days)))
    anchors = {name: _anchor_days(window, column, value) for name, column, value in _CALENDAR_ANCHORS}
    frame = pd.DataFrame({
        "counterparty": events.counterparty.fillna("").astype(str).to_numpy(),
        "category": events.category.fillna("").astype(str).to_numpy(),
        "direction": events.direction.to_numpy(int),
        "day": _to_int(events.date),
        "amount": events.amount.to_numpy(float),
    })
    streams = []
    for (counterparty, direction, category), group in frame.groupby(
            ["counterparty", "direction", "category"], sort=True):
        days = group["day"].to_numpy(np.int64)
        if len(np.unique(days)) != len(days):
            continue  # leave bursts intact in residuals until schedules model multiplicity
        min_occ = _MIN_OCCURRENCES + (_FALLBACK_OCCURRENCES if counterparty == "" else 0)
        stream = _group_stream(str(counterparty), int(direction), str(category), days,
                               group["amount"].to_numpy(float), window, anchors, min_occ)
        if stream is not None:
            streams.append(stream)
    return sorted(streams, key=lambda s: s.key)


def _assign_rows(events, streams):
    """Rows explained by a detected schedule; the complement is the residual donor pool."""
    assigned = np.zeros(len(events), dtype=bool)
    if not len(events) or not streams:
        return assigned
    day = _to_int(events.date)
    counterparty = events.counterparty.fillna("").astype(str).to_numpy()
    category = events.category.fillna("").astype(str).to_numpy()
    direction = events.direction.to_numpy(int)
    for stream in streams:
        mask = ((counterparty == stream.counterparty) & (category == stream.category)
                & (direction == stream.direction))
        assigned |= mask & np.isin(day, stream.days)
    return assigned


def _complete_weeks(history):
    days = _to_int(history.dates)
    known = np.asarray(history.known, dtype=bool)
    week = _week_starts(days)
    return [int(start) for start in np.unique(week)
            if np.flatnonzero(week == start).size == 7 and known[week == start].all()]


def _residual_by_week(residual, history):
    complete = set(_complete_weeks(history))
    if not complete:
        return [], {}
    day = _to_int(residual.date)
    week = _week_starts(day)
    by_week = {int(start): [] for start in complete}  # silence is observed exposure, too
    for week_start, stamp, direction, amount, category, counterparty in zip(
            week.tolist(), day.tolist(), residual.direction.to_numpy(int),
            residual.amount.to_numpy(float),
            residual.category.fillna("").astype(str).to_numpy(),
            residual.counterparty.fillna("").astype(str).to_numpy()):
        if week_start not in complete:
            continue
        by_week.setdefault(int(week_start), []).append(
            (int(stamp - week_start), int(direction), float(amount), category or "unknown", counterparty))
    weeks = sorted(by_week)
    return weeks, by_week


def _week_bootstrap(weeks, by_week, targets, dates, allowed, rng):
    """Whole-week donor bootstrap: keep each donor week's intra-week burst shape."""
    first, last = int(dates[0]), int(dates[-1])
    rows = []
    for target in targets:
        donor = weeks[int(rng.integers(len(weeks)))]
        for offset, direction, amount, category, counterparty in by_week[donor]:
            day = int(target) + offset
            if not first <= day <= last or not allowed[day - first]:
                continue
            rows.append(dict(day=day - first + 1, direction=direction, amount=amount,
                             category=category, counterparty=counterparty))
    return rows


def _pick_category(weights, rng):
    marks = sorted(weights)
    if not marks:
        return "unknown"
    values = np.array([weights[mark] for mark in marks], dtype=float)
    index = int(np.searchsorted(np.cumsum(values) / values.sum(), rng.random(), side="right"))
    return marks[min(index, len(marks) - 1)]


def _count_model(allowed, rates, marks, draw_amount, rng):
    """Small workday count model: Poisson events per direction, pooled marks and amounts."""
    rows = []
    for offset in np.flatnonzero(allowed).tolist():
        for direction in (0, 1):
            for _ in range(int(rng.poisson(max(0.0, float(rates[direction]))))):
                category = _pick_category(marks[direction], rng)
                rows.append(dict(day=offset + 1, direction=direction,
                                 amount=float(draw_amount(direction, category)),
                                 category=category, counterparty=""))
    return rows


def _cap_rows(rows, cap, rng):
    """Explicit per-day cap; returns the kept rows and how many were clipped."""
    if len(rows) <= cap:
        return rows, 0
    by_day = {}
    for row in rows:
        by_day.setdefault(int(row["day"]), []).append(row)
    kept, clipped = [], 0
    for day in sorted(by_day):
        items = by_day[day]
        if len(items) <= cap:
            kept.extend(items)
            continue
        for index in np.sort(rng.choice(len(items), cap, replace=False)).tolist():
            kept.append(items[int(index)])
        clipped += len(items) - cap
    return kept, clipped


def _shrunk_occurrence(stream, priors):
    prior = priors.get((stream.direction, stream.category, stream.kind), {}).get(
        "p_occur", _DEFAULT_OCCURRENCE)
    value = (stream.occurrences + _PRIOR_STRENGTH * float(prior)) / (stream.due + _PRIOR_STRENGTH)
    return float(min(1.0, max(0.05, value)))


def _stream_amount(stream, history, priors, amounts, rng):
    """Local amounts when the stream has enough of them, else its own level times the
    pooled relative amounts of the same mark and schedule kind."""
    prior = priors.get((stream.direction, stream.category, stream.kind))
    level = float(np.median(stream.amounts)) if len(stream.amounts) else 0.0
    if prior is not None and level > 0 and len(stream.amounts) < _MIN_LOCAL_AMOUNTS \
            and len(prior["amounts"]):
        return float(rng.choice(prior["amounts"]) * level)
    if len(stream.amounts):
        return float(rng.choice(stream.amounts))
    return float(amounts.sample(history, stream.direction, stream.category, 1, rng)[0])


def _snap(day, first, last, allowed):
    """Nearest allowed day; workday calendars move weekend/holiday anchors."""
    for step in (0, 1, -1, 2, -2, _SNAP_DAYS, -_SNAP_DAYS):
        candidate = day + step
        if first <= candidate <= last and allowed[candidate - first]:
            return candidate
    return None


def _stream_plan(stream, dates, allowed, horizon_anchors, first, last):
    """Candidate day per (occurrence anchor, observed timing shift); -1 means not in horizon."""
    if stream.kind == "weekly":
        anchors = (np.unique(_week_starts(dates)) + stream.anchor).tolist()
    elif stream.kind == "monthly_dom":
        anchors = _month_day(np.unique(_month_index(dates)), stream.anchor).tolist()
    else:
        table = horizon_anchors[stream.anchor]
        anchors = [table[m] for m in np.unique(_month_index(dates)).tolist() if m in table]
    shifts = stream.shifts if len(stream.shifts) else np.zeros(1, dtype=np.int64)
    plan = []
    fulfilled = set(stream.periods.tolist())
    for anchor in sorted(int(value) for value in anchors):
        period = anchor - int(stream.anchor) if stream.kind == "weekly" else int(_month_index(np.array([anchor]))[0])
        if period in fulfilled:
            continue
        days = []
        for shift in shifts.tolist():
            day = anchor + int(shift)
            snapped = _snap(day, first, last, allowed) if first <= day <= last else None
            days.append(-1 if snapped is None else snapped)  # never pull an occurrence into the horizon
        plan.append(days)
    return plan


class Model:
    """Recurring-schedule generator with a disjoint residual bootstrap."""

    def __init__(self, options: FitOptions | None = None):
        self.options = options or FitOptions()
        self.amounts = ConditionalAmounts()
        self.priors: dict = {}
        self.residual_rates: dict = {}
        self.residual_marks: dict = {}
        self.diagnostics: dict = {}

    def fit(self, histories: list) -> "Model":
        """Fit schedule priors, amount pools and residual rates on the supplied prefixes only.

        Whole histories are processed until ``FitOptions.max_training_rows`` events are seen;
        ``diagnostics["training_rows_truncated"]`` reports whether the cap stopped the scan.
        """
        histories = list(histories)
        self.amounts = ConditionalAmounts().fit(histories)
        pools: dict = {}
        occurrence: dict = {}
        kind_counts: Counter = Counter()
        rate_events: dict = {}
        rate_days: dict = {}
        mark_counts: dict = {}
        rows = residual_rows = 0
        truncated = False
        for history in histories:
            if rows >= self.options.max_training_rows:
                truncated = True
                break
            events = history.events
            rows += len(events)
            window = history.dates[history.known]
            streams = _detect_streams(events, window)
            residual = events[~_assign_rows(events, streams)]
            residual_rows += len(residual)
            for stream in streams:
                kind_counts[stream.kind] += 1
                key = (stream.direction, stream.category, stream.kind)
                occurrence.setdefault(key, []).append(stream.p_occur)
                level = float(np.median(stream.amounts)) if len(stream.amounts) else 0.0
                if level > 0:  # relative amounts so sparse streams keep their own level
                    pools.setdefault(key, []).extend((stream.amounts / level).tolist())
            exposure = max(1, int(np.asarray(history.allowed(window)).sum()))
            for direction in (0, 1):
                count = int((residual.direction == direction).sum())
                for key in ((history.industry, direction), ("*", direction)):
                    rate_events[key] = rate_events.get(key, 0) + count
                    rate_days[key] = rate_days.get(key, 0) + exposure
                marks = residual.loc[residual.direction == direction, "category"].fillna("").astype(str)
                for category in marks:
                    for key in ((history.industry, direction), ("*", direction)):
                        counter = mark_counts.setdefault(key, Counter())
                        counter[category or "unknown"] += 1
        self.priors = {key: dict(p_occur=float(np.clip(np.mean(occurrence[key]), 0.05, 0.95)),
                                 amounts=np.asarray(values[-_MAX_POOL:], dtype=float))
                       for key, values in pools.items()}
        self.residual_rates = {key: rate_events[key] / rate_days[key] for key in rate_events}
        self.residual_marks = mark_counts
        self.diagnostics = dict(histories=len(histories), training_rows=int(rows),
                                training_rows_truncated=bool(truncated),
                                streams=int(sum(kind_counts.values())),
                                stream_kinds=dict(sorted(kind_counts.items())),
                                residual_rows=int(residual_rows),
                                amount_pools=len(self.priors))
        return self

    def sample(self, history, horizon: int, n_paths: int, rng: np.random.Generator) -> EventPaths:
        horizon, n_paths = int(horizon), int(n_paths)
        if int(self.options.max_events_per_day) < 1:
            raise ValueError("max_events_per_day cap must be at least one")
        dates = np.asarray(history.as_of + np.arange(1, horizon + 1) * np.timedelta64(1, "D"),
                           dtype="datetime64[D]")
        stamps = _to_int(dates)
        allowed = np.asarray(history.allowed(dates), dtype=bool)
        window = history.dates[history.known]
        events = history.events
        streams = _detect_streams(events, window)
        assigned = _assign_rows(events, streams)
        residual = events[~assigned].reset_index(drop=True)
        probabilities = [_shrunk_occurrence(stream, self.priors) for stream in streams]
        horizon_anchors = {name: _anchor_days(stamps, column, value)
                           for name, column, value in _CALENDAR_ANCHORS}
        first, last = int(stamps[0]), int(stamps[-1])
        plans = [_stream_plan(stream, stamps, allowed, horizon_anchors, first, last) for stream in streams]
        target_weeks = np.unique(_week_starts(stamps)).tolist()
        weeks, by_week = _residual_by_week(residual, history)
        local = len(residual) >= _MIN_LOCAL_RATE_ROWS
        source = "local_weeks" if weeks else ("local_rate" if local else "pooled")
        rates, marks = ({0: 0.0, 1: 0.0}, {0: {}, 1: {}}) if weeks else self._rate_model(history, residual, local)
        clipped = stream_events = residual_events = 0
        records = []
        for path in range(n_paths):
            rows = []
            for stream, plan, probability in zip(streams, plans, probabilities):
                seen = set()
                for candidates in plan:
                    day = candidates[int(rng.integers(len(candidates)))]
                    if day < 0 or day in seen:
                        continue
                    seen.add(day)
                    if rng.random() >= probability:
                        continue
                    rows.append(dict(path=path, day=day - first + 1, direction=stream.direction,
                                     amount=_stream_amount(stream, history, self.priors, self.amounts, rng),
                                     category=stream.category or "unknown",
                                     counterparty=stream.counterparty, known_event_id=""))
            stream_events += len(rows)
            if source == "local_weeks":
                week_rows = _week_bootstrap(weeks, by_week, target_weeks, stamps, allowed, rng)
            else:
                week_rows = _count_model(allowed, rates, marks,
                                         lambda direction, category: self.amounts.sample(
                                             history, direction, category, 1, rng)[0], rng)
            residual_events += len(week_rows)
            for row in week_rows:
                rows.append(dict(row, path=path, known_event_id=""))
            rows, cut = _cap_rows(rows, int(self.options.max_events_per_day), rng)
            clipped += cut
            records.extend(rows)
        diagnostics = dict(paths=n_paths, horizon=horizon, streams=len(streams),
                           stream_kinds=dict(sorted(Counter(s.kind for s in streams).items())),
                           stream_probabilities=sorted(float(p) for p in probabilities),
                           assigned_rows=int(assigned.sum()), residual_rows=int(len(residual)),
                           residual_source=source, stream_events=int(stream_events),
                           residual_events=int(residual_events), clipped_events=int(clipped),
                           max_events_per_day=int(self.options.max_events_per_day))
        return EventPaths.from_records(history, horizon, n_paths, records, diagnostics)

    def _rate_model(self, history, residual, local):
        """Per-direction workday rates and mark weights for the two rate fallbacks."""
        exposure = max(1, int(np.asarray(history.allowed(history.dates[history.known])).sum()))
        rates, marks = {}, {}
        for direction in (0, 1):
            if local:
                rates[direction] = int((residual.direction == direction).sum()) / exposure
                columns = residual.loc[residual.direction == direction, "category"].fillna("").astype(str)
                marks[direction] = Counter(category or "unknown" for category in columns)
            else:
                rates[direction] = float(self.residual_rates.get((history.industry, direction),
                                                                 self.residual_rates.get(("*", direction), 0.0)))
                weights = self.residual_marks.get((history.industry, direction),
                                                  self.residual_marks.get(("*", direction), Counter()))
                marks[direction] = Counter(weights)
        return rates, marks

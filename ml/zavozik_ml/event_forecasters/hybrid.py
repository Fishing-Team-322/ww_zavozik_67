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

Emitted amounts carry one bounded level correction per direction (recent 91-day
median over the 364-day baseline, shrunk and clipped) and residual weeks are
drawn with a monthly-phase similarity bonus mixed into the uniform donor choice.
Both are reported in ``EventPaths.diagnostics`` and never change counts or dates.
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
PHASE_WEIGHT = 0.5  # mix of phase-similarity against uniform donors; 0.0 disables it
_PHASE_SAME, _PHASE_ADJACENT, _PHASE_OTHER = 1.0, 0.5, 0.2
_PHASE_EOM_DECAY_DAYS = 5.0
_LEVEL_RECENT_DAYS = 91
_LEVEL_BASELINE_DAYS = 364
_LEVEL_MIN_AMOUNTS = 8
_LEVEL_SHRINKAGE = 20.0
_LEVEL_BOUNDS = (0.8, 1.25)


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


def _month_phase(days):
    """Position in the month: 0 for days 1-10, 1 for 11-20, 2 for 21-end."""
    dom = _day_of_month(days)
    return np.where(dom <= 10, 0, np.where(dom <= 20, 1, 2))


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


def _week_bootstrap(weeks, by_week, targets, dates, allowed, rng, scores=None):
    """Whole-week donor bootstrap: keep each donor week's intra-week burst shape."""
    first, last = int(dates[0]), int(dates[-1])
    if scores is None:  # caller may precompute the calendar-only scores once per sample
        scores = _phase_scores(weeks, targets, first, last, allowed)
    rows = []
    for row, target in enumerate(targets):
        donor = weeks[_donor_index(scores[row], rng)]
        for offset, direction, amount, category, counterparty in by_week[donor]:
            day = int(target) + offset
            if not first <= day <= last or not allowed[day - first]:
                continue
            rows.append(dict(day=day - first + 1, direction=direction, amount=amount,
                             category=category, counterparty=counterparty))
    return rows


def _day_phase_weight(day, donor_days):
    """Similarity of one target day to donor days: phase band times end-of-month proximity."""
    target_phase = int(_month_phase(np.array([day], dtype=np.int64))[0])
    gap = np.abs(target_phase - _month_phase(donor_days))
    similarity = np.where(gap == 0, _PHASE_SAME, np.where(gap == 1, _PHASE_ADJACENT, _PHASE_OTHER))
    target_dom = int(_day_of_month(np.array([day], dtype=np.int64))[0])
    proximity = np.exp(-np.abs(target_dom - _day_of_month(donor_days)) / _PHASE_EOM_DECAY_DAYS)
    return similarity * proximity


def _phase_scores(weeks, targets, first, last, allowed):
    """Per donor week, mean similarity of its shape to the target week's allowed days.

    A target day is compared with the donor day at the same intra-week offset because the
    bootstrap re-plays the whole donor week; that keeps weekly dependence intact.
    """
    weeks = np.asarray(weeks, dtype=np.int64)
    donor_days = weeks[:, None] + np.arange(7, dtype=np.int64)[None, :]
    scores = np.zeros((len(targets), len(weeks)))
    for row, target in enumerate(int(value) for value in targets):
        offsets = [offset for offset in range(7)
                   if first <= target + offset <= last and allowed[target + offset - first]]
        if not offsets:
            continue
        for offset in offsets:
            scores[row] += _day_phase_weight(target + offset, donor_days[:, offset])
        scores[row] /= len(offsets)
    return scores


def _donor_index(scores, rng):
    """Uniform-plus-phase donor draw; every donor keeps a positive uniform share."""
    count = len(scores)
    if PHASE_WEIGHT <= 0.0:
        return int(rng.integers(count))
    total = float(scores.sum()) if np.isfinite(scores).all() else 0.0
    weights = np.full(count, 1.0 / count)
    if total > 0.0:
        weights = (1.0 - PHASE_WEIGHT) * weights + PHASE_WEIGHT * (scores / total)
    return int(rng.choice(count, p=weights / weights.sum()))


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


def _level_factor(history, direction):
    """Bounded recent-over-baseline median level for one direction at this cutoff.

    Positive amounts only, from origin-visible events. Fewer than eight positive
    amounts in either window (or an empty history) leaves the level untouched.
    """
    events = history.events
    if not len(events):
        return 1.0
    mask = (events.direction.to_numpy(int) == int(direction)) & (events.amount.to_numpy(float) > 0)
    if not mask.any():
        return 1.0
    day = _to_int(events.date)[mask]
    amount = events.amount.to_numpy(float)[mask]
    as_of = int(_to_int(np.array([history.as_of], dtype="datetime64[D]"))[0])
    recent = amount[day > as_of - _LEVEL_RECENT_DAYS]
    baseline = amount[day > as_of - _LEVEL_BASELINE_DAYS]
    if len(recent) < _LEVEL_MIN_AMOUNTS or len(baseline) < _LEVEL_MIN_AMOUNTS:
        return 1.0
    reference = float(np.median(baseline))
    if reference <= 0.0:
        return 1.0
    ratio = float(np.median(recent)) / reference
    weight = len(recent) / (len(recent) + _LEVEL_SHRINKAGE)
    factor = float(np.exp(weight * np.log(ratio)))
    return float(np.clip(factor, *_LEVEL_BOUNDS))


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
        week_scores = _phase_scores(weeks, target_weeks, first, last, allowed) if weeks else None
        level = {direction: _level_factor(history, direction) for direction in (0, 1)}
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
                week_rows = _week_bootstrap(weeks, by_week, target_weeks, stamps, allowed, rng,
                                            week_scores)
            else:
                week_rows = _count_model(allowed, rates, marks,
                                         lambda direction, category: self.amounts.sample(
                                             history, direction, category, 1, rng)[0], rng)
            residual_events += len(week_rows)
            for row in week_rows:
                rows.append(dict(row, path=path, known_event_id=""))
            rows, cut = _cap_rows(rows, int(self.options.max_events_per_day), rng)
            for row in rows:  # exactly one level correction per event, after every scaling step
                row["amount"] = float(row["amount"]) * level[int(row["direction"])]
            clipped += cut
            records.extend(rows)
        diagnostics = dict(paths=n_paths, horizon=horizon, streams=len(streams),
                           stream_kinds=dict(sorted(Counter(s.kind for s in streams).items())),
                           stream_probabilities=sorted(float(p) for p in probabilities),
                           assigned_rows=int(assigned.sum()), residual_rows=int(len(residual)),
                           residual_source=source, stream_events=int(stream_events),
                           residual_events=int(residual_events), clipped_events=int(clipped),
                           level_factor={str(direction): float(level[direction]) for direction in (0, 1)},
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

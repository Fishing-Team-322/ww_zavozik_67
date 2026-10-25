"""Whole-event, calendar-aligned block resampling for the event benchmark.

The donor unit is one *complete observed day* (or one calendar week without
any unknown day). Every direction, mark, amount and company-local counterparty
of a block moves together, so intra-day and intra-week dependence survives
instead of being re-shuffled event by event.

Back-off ladder: company-local donors first, then fit-only industry donors, then
fit-only global donors. A local history with fewer than three event-bearing days
is treated as too short/empty and backs off (reported as ``local_backoff``).
Cross-company donors are stored company-relative (amount divided by the donor's
own per-direction scale) and rescaled by the target company's scale at draw
time; their counterparties and operation IDs are never transferred.

Calendar discipline: a donor day must be complete *and* admissible for its own
company, so a holiday is never replayed as a quiet target workday. Missing days
are never donors and a week containing an unknown day is rejected as a block
instead of being read as silence. Target days outside ``history.allowed`` are
never emitted and their count is reported.

Monthly phase: donors are not matched on weekday alone. Each candidate also
scores by its position inside the month (days 1-10 / 11-20 / 21-end) and by its
proximity to the target day, and that score is mixed with the uniform choice, so
a monthly obligation keeps landing near its day-of-month while no donor ever
becomes impossible.

Level correction: the emitted amounts of each direction are multiplied once by a
bounded factor built from the median positive amount of the last 91 known days
over the last 364. It is applied after the pool rescaling, so a company-relative
donor amount is never scaled twice; counts, dates, marks and counterparties are
untouched and the factor is reported in the sample diagnostics.

Stated limits:
* Monthly phase matching shifts the day-of-month distribution, but a direction
  whose donors carry an event on *every* admissible day keeps its event on every
  target day (the phase only changes which donor block is replayed).
* Levels and trends inside the donor window are replayed apart from the bounded
  recent/baseline correction; drifts steeper than the [0.8, 1.25] clip are not
  extrapolated.
* Whole-week mode needs a donor week whose admissible weekdays cover the target
  week; when none covers it the horizon falls back to single-day blocks and the
  fallback is reported.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .core import EventPaths, FitOptions

# Weekday bit: (days since 1970-01-01 + 3) % 7, 0 = Monday.
_WEEKDAY_OFFSET = 3
# Lag-1 within-week residual correlation above which whole-week blocks are used.
_WEEK_BLOCK_THRESHOLD = 0.2
_MIN_DEPENDENCE_DAYS = 20
_MIN_DEPENDENCE_PAIRS = 8
# A local history with fewer event-bearing days cannot be resampled on its own
# and backs off to fit-only industry/global donors instead.
_MIN_LOCAL_EVENT_DAYS = 3
# Share of the donor selection mass given to the month-phase score; the rest
# stays uniform so sparse pools keep working and no donor becomes impossible.
PHASE_WEIGHT = 0.5
# Month-phase score by |phase(target) - phase(donor)| in {0, 1, 2} and the decay
# of the day-of-month distance.
_PHASE_SAME, _PHASE_ADJACENT, _PHASE_FAR = 1.0, 0.5, 0.2
_PHASE_PROXIMITY_DAYS = 5.0
# Bounded monetary level correction over the last 91 known days against 364.
_LEVEL_RECENT_DAYS = 91
_LEVEL_BASELINE_DAYS = 364
_LEVEL_MIN_POSITIVE = 8
_LEVEL_SHRINK = 20.0
_LEVEL_MIN_FACTOR, _LEVEL_MAX_FACTOR = 0.8, 1.25


def _day_numbers(dates) -> np.ndarray:
    return np.asarray(dates, dtype="datetime64[D]").astype(np.int64)


def _day_of_month(dates) -> np.ndarray:
    dates = np.asarray(dates, dtype="datetime64[D]")
    return (dates - dates.astype("datetime64[M]")).astype(np.int64) + 1


def _weekday(dates) -> np.ndarray:
    return (_day_numbers(dates) + _WEEKDAY_OFFSET) % 7


def _week_ids(dates) -> np.ndarray:
    return (_day_numbers(dates) + _WEEKDAY_OFFSET) // 7


def _mark(value) -> str:
    text = "" if value is None else str(value)
    if not text or text.lower() == "nan" or text.lower() == "none":
        return "unknown"
    return text


def _identity(value) -> str:
    text = "" if value is None else str(value)
    return "" if not text or text.lower() == "nan" or text.lower() == "none" else text


def _weekly_dependence(history):
    """Lag-1 correlation of weekday-centred daily counts inside the same week.

    Only admissible days enter the estimate, so calendar holidays cannot look
    like genuine week-level swings. ``None`` means the history is too short or
    too flat to judge; callers then use single-day blocks (or the fit-time
    pooled estimate).
    """
    dates = np.asarray(history.dates, dtype="datetime64[D]")
    base = np.asarray(history.known, dtype=bool) & np.asarray(history.allowed(dates), dtype=bool)
    if int(base.sum()) < _MIN_DEPENDENCE_DAYS:
        return None
    totals = np.zeros(len(dates), dtype=np.float64)
    events = history.events
    if len(events):
        np.add.at(totals, np.searchsorted(dates, events.date.to_numpy(dtype="datetime64[D]")), 1.0)
    weekday = _weekday(dates)
    residual = np.zeros(len(dates), dtype=np.float64)
    for value in range(7):
        selected = base & (weekday == value)
        if int(selected.sum()) >= 3:
            residual[selected] = totals[selected] - totals[selected].mean()
    weeks = _week_ids(dates)
    pairs = base[:-1] & base[1:] & (weeks[:-1] == weeks[1:])
    left, right = residual[:-1][pairs], residual[1:][pairs]
    if len(left) < _MIN_DEPENDENCE_PAIRS or left.std() == 0 or right.std() == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def _mean_dependence(histories):
    scores = [score for score in (_weekly_dependence(h) for h in histories) if score is not None]
    return float(np.mean(scores)) if scores else None


def _month_phase(day_of_month) -> np.ndarray:
    """0 for days 1-10, 1 for 11-20, 2 for 21 to end of month."""
    dom = np.asarray(day_of_month, dtype=np.int64)
    return np.where(dom <= 10, 0, np.where(dom <= 20, 1, 2))


def _phase_weights(target_day_of_month, donor_day_of_month) -> np.ndarray:
    """Month-position agreement, decayed by the distance to the target day."""
    gap = np.abs(_month_phase(target_day_of_month) - _month_phase(donor_day_of_month))
    phase = np.where(gap == 0, _PHASE_SAME, np.where(gap == 1, _PHASE_ADJACENT, _PHASE_FAR))
    distance = np.abs(np.asarray(target_day_of_month, dtype=np.int64)
                      - np.asarray(donor_day_of_month, dtype=np.int64))
    return phase * np.exp(-distance / _PHASE_PROXIMITY_DAYS)


def _mixed_weights(score) -> np.ndarray:
    """Blend a phase score with the uniform choice so every donor stays possible."""
    weights = np.asarray(score, dtype=np.float64)
    uniform = np.full(weights.shape, 1.0 / len(weights), dtype=np.float64)
    total = float(weights.sum())
    if not np.isfinite(total) or total <= 0.0:
        return uniform
    return (1.0 - PHASE_WEIGHT) * uniform + PHASE_WEIGHT * (weights / total)


def _weighted_pick(weights, rng) -> int:
    """One donor position drawn from ``weights`` with the caller's generator."""
    cumulative = np.cumsum(weights)
    position = int(np.searchsorted(cumulative, rng.random() * cumulative[-1], side="right"))
    return min(position, len(weights) - 1)


def _level_factor(history, direction) -> float:
    """Bounded monetary level correction for one direction of one history.

    Only positive amounts visible at this cutoff enter; a window with fewer than
    ``_LEVEL_MIN_POSITIVE`` of them leaves the direction untouched (``1.0``), and
    the shrunk median ratio is clipped so one busy fortnight cannot rescale the
    whole horizon.
    """
    dates = np.asarray(history.dates, dtype="datetime64[D]")
    events = history.events
    if not len(events):
        return 1.0
    offset = (events.date.to_numpy(dtype="datetime64[D]") - dates[0]).astype(np.int64)
    positive = (events.direction.to_numpy(int) == int(direction)) & (events.amount.to_numpy(float) > 0.0)
    offset, amount = offset[positive], events.amount.to_numpy(float)[positive]
    recent = amount[offset >= max(0, len(dates) - _LEVEL_RECENT_DAYS)]
    baseline = amount[offset >= max(0, len(dates) - _LEVEL_BASELINE_DAYS)]
    if len(recent) < _LEVEL_MIN_POSITIVE or len(baseline) < _LEVEL_MIN_POSITIVE:
        return 1.0
    ratio = float(np.median(recent) / np.median(baseline))
    if not np.isfinite(ratio) or ratio <= 0.0:
        return 1.0
    weight = len(recent) / (len(recent) + _LEVEL_SHRINK)
    return float(np.clip(np.exp(weight * np.log(ratio)), _LEVEL_MIN_FACTOR, _LEVEL_MAX_FACTOR))


class _DayStore:
    """Complete observed days with their events, one contiguous group per day."""

    def __init__(self):
        self.dates: list = []
        self.weekdays: list[int] = []
        self.bounds: list[int] = [0]
        self.direction: list[int] = []
        self.amount: list[float] = []
        self.category: list[str] = []
        self.counterparty: list[str] = []

    def add_day(self, date, weekday, rows):
        self.dates.append(np.datetime64(date, "D"))
        self.weekdays.append(int(weekday))
        for direction, amount, category, counterparty in rows:
            self.direction.append(int(direction))
            self.amount.append(amount)
            self.category.append(category)
            self.counterparty.append(counterparty)
        self.bounds.append(len(self.direction))

    def freeze(self):
        self.dates = np.asarray(self.dates, dtype="datetime64[D]")
        self.weekdays = np.asarray(self.weekdays, dtype=np.int64)
        self.bounds = np.asarray(self.bounds, dtype=np.int64)
        self.direction = np.asarray(self.direction, dtype=np.int64)
        self.amount = np.asarray(self.amount, dtype=np.float64)
        self.category = np.asarray(self.category, dtype=object)
        self.counterparty = np.asarray(self.counterparty, dtype=object)
        return self

    def events(self, day):
        offset = int(self.bounds[day])
        stop = int(self.bounds[day + 1])
        return (self.direction[offset:stop], self.amount[offset:stop],
                self.category[offset:stop], self.counterparty[offset:stop])


@dataclass(frozen=True)
class _BlockPool:
    """Donor day and week blocks over one shared day store.

    ``week_blocks`` holds ``(covered weekdays, weekday -> day)`` pairs; the
    covered set is what a target week run must fit into so a donor holiday is
    never transplanted as a quiet target workday.
    """

    store: _DayStore
    day_blocks: np.ndarray
    week_blocks: tuple
    rescale: bool
    weeks_unknown: int = 0

    def by_weekday(self, weekday):
        if not len(self.day_blocks):
            return self.day_blocks
        return self.day_blocks[self.store.weekdays[self.day_blocks] == weekday]

    @property
    def event_days(self) -> int:
        return int((np.diff(self.store.bounds)[self.day_blocks] > 0).sum())

    def visible(self, as_of):
        """Restrict donors to days known at ``as_of`` (no future knowledge)."""
        days = self.day_blocks
        if len(days):
            days = days[self.store.dates[days] <= as_of]
        weeks = tuple((cover, block) for cover, block in self.week_blocks
                      if all(self.store.dates[day] <= as_of for day in block.values()))
        if len(days) == len(self.day_blocks) and len(weeks) == len(self.week_blocks):
            return self
        return _BlockPool(self.store, days, weeks, self.rescale, self.weeks_unknown)


def _pool_events(history, dates, rescale):
    """One history's events as day-sorted columns, normalised for pooling.

    Cross-company pools are stored company-relative (amount divided by the
    donor's own per-direction scale) and lose the donor's counterparties.
    """
    events = history.events
    if not len(events):
        empty_float = np.empty(0, dtype=np.float64)
        empty_object = np.empty(0, dtype=object)
        return (np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64),
                empty_float, empty_object, empty_object)
    days = np.searchsorted(dates, events.date.to_numpy(dtype="datetime64[D]"))
    order = np.argsort(days, kind="stable")
    directions = events.direction.to_numpy(int)[order]
    amounts = events.amount.to_numpy(float)[order]
    marks = np.asarray([_mark(value) for value in events.category.to_numpy(object)], dtype=object)[order]
    if rescale:
        scales = np.array([history.amount_scale(0), history.amount_scale(1)], dtype=np.float64)
        amounts = amounts / scales[directions]
        counterparts = np.full(len(days), "", dtype=object)
    else:
        raw = (events.counterparty.to_numpy(object) if "counterparty" in events
               else np.full(len(events), "", dtype=object))
        counterparts = np.asarray([_identity(value) for value in raw], dtype=object)[order]
    return days[order], directions, amounts, marks, counterparts


def _build_pool(histories, budget, rescale):
    """Collect whole-day and whole-week donor blocks, one company at a time.

    ``budget`` bounds the number of most recent usable days per company for
    fit-time cross-company pools; ``None`` keeps every usable day (local
    donors). Donor days must be complete *and* admissible for that company, so
    a calendar holiday is never replayed as a quiet workday.
    """
    store = _DayStore()
    day_blocks: list[int] = []
    week_blocks: list[tuple] = []
    weeks_unknown = 0
    for history in histories:
        dates = np.asarray(history.dates, dtype="datetime64[D]")
        weekday = _weekday(dates)
        week = _week_ids(dates)
        known = np.asarray(history.known, dtype=bool)
        usable = np.flatnonzero(known & np.asarray(history.allowed(dates), dtype=bool))
        if not len(usable):
            continue
        if budget is not None and len(usable) > budget:
            usable = usable[-int(budget):]
        event_days, directions, amounts, marks, counterparts = _pool_events(history, dates, rescale)
        day_of = {}
        for day in usable:
            start = int(np.searchsorted(event_days, day, side="left"))
            stop = int(np.searchsorted(event_days, day, side="right"))
            rows = list(zip(directions[start:stop].tolist(), amounts[start:stop].tolist(),
                            marks[start:stop].tolist(), counterparts[start:stop].tolist()))
            store.add_day(dates[day], int(weekday[day]), rows)
            index = len(store.dates) - 1
            day_of[int(day)] = index
            day_blocks.append(index)
        gap_weeks = set(week[~known].tolist())
        groups: dict[int, dict[int, int]] = {}
        for day in usable:
            groups.setdefault(int(week[day]), {})[int(weekday[day])] = int(day)
        for key, mapping in groups.items():
            if key in gap_weeks:
                # A block containing an unknown day is rejected, never read as silence.
                weeks_unknown += 1
                continue
            block = {value: day_of[day] for value, day in mapping.items()}
            week_blocks.append((frozenset(block), block))
    return _BlockPool(store.freeze(), np.asarray(day_blocks, dtype=np.int64),
                      tuple(week_blocks), bool(rescale), weeks_unknown)


def _pick_day(levels, weekday):
    for name, pool in levels:
        index = pool.by_weekday(weekday)
        if len(index):
            return pool, index, name, False
    for name, pool in levels:
        if len(pool.day_blocks):
            return pool, pool.day_blocks, name, True
    return None, None, "none", False


def _week_plan(levels, runs, weekday, allowed):
    """Pick a donor-week pool per target week run, or None when coverage fails."""
    plan = []
    for run in runs:
        needed = frozenset(int(weekday[day]) for day in run if allowed[day])
        if not needed:
            continue
        for name, pool in levels:
            keys = np.asarray([position for position, (cover, _) in enumerate(pool.week_blocks)
                               if needed <= cover], dtype=np.int64)
            if len(keys):
                plan.append((run, pool, name, keys))
                break
        else:
            return None
    return plan


def _week_weights(pool, keys, run, weekday, allowed, target_day_of_month) -> np.ndarray:
    """Donor-week selection weights for one target week run.

    A candidate week is scored by the mean per-day month-phase weight over the
    run's admissible days, so the block still moves as a whole and the weekly
    dependence survives.
    """
    days = [int(day) for day in run if allowed[day]]
    target = np.asarray(target_day_of_month, dtype=np.int64)[days]
    score = np.empty(len(keys), dtype=np.float64)
    for position, key in enumerate(keys):
        block = pool.week_blocks[int(key)][1]
        donor = np.array([_day_of_month(pool.store.dates[block[int(weekday[day])]]) for day in days],
                         dtype=np.int64)
        score[position] = float(np.mean(_phase_weights(target, donor)))
    return _mixed_weights(score)


def _week_runs(week_ids, horizon):
    runs, start = [], 0
    for position in range(1, horizon + 1):
        if position == horizon or week_ids[position] != week_ids[start]:
            runs.append(np.arange(start, position))
            start = position
    return runs


def _cap_mask(days, cap):
    """Keep at most ``cap`` events per day, preferring the first drawn ones."""
    count = len(days)
    if count == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(days, kind="stable")
    position = np.empty(count, dtype=np.int64)
    position[order] = np.arange(count)
    first = np.searchsorted(days[order], days)
    return (position - first) < cap


class Model:
    """Whole-event block resampler over calendar-aligned days and weeks."""

    def __init__(self, options: FitOptions | None = None):
        self.options = options or FitOptions()
        self.industry_pools: dict[str, _BlockPool] = {}
        self.global_pool: _BlockPool | None = None
        self.weekly_dependence: float | None = None
        self.fit_diagnostics: dict = {}

    def fit(self, histories):
        histories = list(histories)
        budget = max(1, int(self.options.max_training_rows) // max(1, len(histories)))
        per_industry: dict[str, list] = {}
        for history in histories:
            per_industry.setdefault(str(history.industry), []).append(history)
        self.industry_pools = {industry: _build_pool(rows, budget, rescale=True)
                               for industry, rows in per_industry.items()}
        self.global_pool = _build_pool(histories, budget, rescale=True)
        self.weekly_dependence = _mean_dependence(histories)
        self.fit_diagnostics = {
            "companies": len(histories),
            "industries": len(self.industry_pools),
            "days_per_company_budget": budget,
            "global_donor_days": int(len(self.global_pool.day_blocks)),
            "global_donor_weeks": len(self.global_pool.week_blocks),
            "global_weeks_rejected_unknown": int(self.global_pool.weeks_unknown),
            "industry_donor_days": int(sum(len(pool.day_blocks) for pool in self.industry_pools.values())),
            "weekly_dependence": self.weekly_dependence,
        }
        return self

    def sample(self, history, horizon: int, n_paths: int, rng: np.random.Generator) -> EventPaths:
        horizon, n_paths = int(horizon), int(n_paths)
        if horizon < 1 or n_paths < 1:
            raise ValueError("positive horizon and path count required")
        dates = np.asarray(history.dates, dtype="datetime64[D]")
        as_of = dates[-1]
        target = as_of + np.arange(1, horizon + 1).astype("timedelta64[D]")
        weekday = _weekday(target)
        week_ids = _week_ids(target)
        target_day_of_month = _day_of_month(target)
        allowed = np.asarray(history.allowed(target), dtype=bool)
        target_scale = np.array([history.amount_scale(0), history.amount_scale(1)], dtype=np.float64)
        level_factor = np.array([_level_factor(history, 0), _level_factor(history, 1)], dtype=np.float64)

        local = _build_pool([history], None, rescale=False).visible(as_of)
        levels: list[tuple[str, _BlockPool]] = []
        local_backoff = None
        if local.event_days >= _MIN_LOCAL_EVENT_DAYS:
            levels.append(("local", local))
        else:
            local_backoff = "empty" if local.event_days == 0 else "short"
        industry_pool = self.industry_pools.get(str(history.industry))
        if industry_pool is not None:
            levels.append(("industry", industry_pool.visible(as_of)))
        if self.global_pool is not None:
            levels.append(("global", self.global_pool.visible(as_of)))

        dependence = _weekly_dependence(history)
        if dependence is None:
            dependence = self.weekly_dependence
        weekly_blocks_wanted = dependence is not None and dependence >= _WEEK_BLOCK_THRESHOLD
        runs = _week_runs(week_ids, horizon)
        plan = _week_plan(levels, runs, weekday, allowed) if weekly_blocks_wanted else None
        use_week = plan is not None
        week_weights = ([_week_weights(pool, keys, run, weekday, allowed, target_day_of_month)
                         for run, pool, _name, keys in plan] if plan else [])
        picks = [_pick_day(levels, value) for value in range(7)]

        cap = max(1, int(self.options.max_events_per_day))
        counts = {"local": 0, "industry": 0, "global": 0, "weekday_relaxed": 0, "none": 0}
        columns = {key: [] for key in ("path", "day", "direction", "amount", "category", "counterparty")}
        clipped_events = 0
        for path in range(n_paths):
            day_parts: list[np.ndarray] = []
            direction_parts: list[np.ndarray] = []
            amount_parts: list[np.ndarray] = []
            category_parts: list[np.ndarray] = []
            counterparty_parts: list[np.ndarray] = []
            if use_week:
                for (run, pool, name, keys), weights in zip(plan, week_weights):
                    block = pool.week_blocks[int(keys[_weighted_pick(weights, rng)])][1]
                    counts[name] += int(np.count_nonzero(allowed[run]))
                    for day in run:
                        if not allowed[day]:
                            continue
                        self._take(pool, block[int(weekday[day])], int(day) + 1, target_scale,
                                   day_parts, direction_parts, amount_parts,
                                   category_parts, counterparty_parts)
            else:
                donors = np.full(horizon, -1, dtype=np.int64)
                owners: list = [None] * horizon
                for value in range(7):
                    days = np.flatnonzero(allowed & (weekday == value))
                    if not len(days):
                        continue
                    pool, index, level, relaxed = picks[value]
                    if pool is None:
                        counts["none"] += len(days)
                        continue
                    counts[level] += len(days)
                    if relaxed:
                        counts["weekday_relaxed"] += len(days)
                    donor_day_of_month = _day_of_month(pool.store.dates[index])
                    for day in days:
                        weights = _mixed_weights(_phase_weights(target_day_of_month[day],
                                                              donor_day_of_month))
                        donors[day] = index[_weighted_pick(weights, rng)]
                        owners[day] = pool
                for day in np.flatnonzero(donors >= 0):
                    self._take(owners[day], int(donors[day]), int(day) + 1, target_scale,
                               day_parts, direction_parts, amount_parts,
                               category_parts, counterparty_parts)
            days_drawn = np.concatenate(day_parts) if day_parts else np.empty(0, dtype=np.int64)
            keep = _cap_mask(days_drawn, cap)
            clipped_events += int((~keep).sum())
            if not len(days_drawn):
                continue
            columns["path"].append(np.full(int(keep.sum()), path, dtype=np.int64))
            columns["day"].append(days_drawn[keep])
            direction = np.concatenate(direction_parts)[keep]
            columns["direction"].append(direction)
            # Level correction is applied exactly once, after every pool rescaling.
            columns["amount"].append(np.concatenate(amount_parts)[keep] * level_factor[direction])
            columns["category"].append(np.concatenate(category_parts)[keep])
            columns["counterparty"].append(np.concatenate(counterparty_parts)[keep])

        if columns["path"]:
            records = {key: np.concatenate(values) for key, values in columns.items()}
            records["known_event_id"] = np.full(len(records["path"]), "", dtype=object)
        else:
            records = {}
        masked_days = int((~allowed).sum())
        diagnostics = {
            "model": "blocks",
            "donor_mode": "week" if use_week else "day",
            "week_blocks_unavailable": bool(weekly_blocks_wanted and plan is None),
            "weekly_dependence": None if dependence is None else float(dependence),
            "target_days": horizon,
            "allowed_days": int(allowed.sum()),
            "masked_days": masked_days,
            "calendar_filtered": bool(masked_days),
            "donor_source_counts": counts,
            "local_event_days": local.event_days,
            "local_backoff": local_backoff,
            "local_donor_days": int(len(local.day_blocks)),
            "local_week_blocks": len(local.week_blocks),
            "cap_events_per_day": cap,
            "clipped_events": clipped_events,
            "generated_events": int(len(records.get("path", []))),
            "phase_weight": float(PHASE_WEIGHT),
            "level_factor": {"0": float(level_factor[0]), "1": float(level_factor[1])},
        }
        return EventPaths.from_records(history, horizon, n_paths, records, diagnostics)

    @staticmethod
    def _take(pool, donor, day, target_scale, day_parts, direction_parts, amount_parts,
              category_parts, counterparty_parts):
        direction, amount, category, counterparty = pool.store.events(donor)
        size = len(direction)
        if not size:
            return
        day_parts.append(np.full(size, day, dtype=np.int64))
        direction_parts.append(direction)
        amount_parts.append(amount if not pool.rescale else amount * target_scale[direction])
        category_parts.append(category)
        counterparty_parts.append(counterparty)

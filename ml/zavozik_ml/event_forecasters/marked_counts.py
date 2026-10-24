"""Marked-count event generator: hurdle counts, smoothed marks, regime amounts.

Research only; nothing here is registered for serving and no probability is
presented as calibrated. The generator deliberately separates the four things
an unconditional count bootstrap conflates:

* **occurrence** - a pooled per-direction hurdle ``P(day has a transaction)``
  fitted by LightGBM on target-day calendar features and origin-visible
  company activity levels;
* **magnitude** - future counts follow a negative binomial whose mean is the
  LightGBM-Poisson fit on those same origin-visible features, and whose
  overdispersion ``r`` is estimated by method of moments on days *held out*
  from that fit (LightGBM's Poisson objective only supplies a mean, never a
  full distribution). When held-out evidence is too thin, or the residual
  variance is at or below Poisson, the law falls back to the documented
  geometric shape ``r = 1`` / the near-Poisson upper bound, and the choice is
  reported in ``diagnostics``;
* **marks** - category shares are smoothed hierarchically
  (company-visible counts -> industry x direction x month-position -> global),
  with a probability floor so rare marks stay reachable; a mark seen only in
  the sampling history still gets mass, an empty pool degrades to ``unknown``;
* **amounts** - ``ConditionalAmounts`` draws condition on direction, mark and
  company scale, and one historical activity block is sampled per scenario and
  applied to the whole path (both directions), so multi-day and cross-direction
  activity-size dependence survives. The block factor is clipped to explicit
  bounds and every clip is counted.

Fit reads only ``EventHistory.events`` - complete days known at the history
cutoff. ``raw_events`` is never used directly, so a gap that was not yet
discovered cannot leak into counts, marks or amounts. Target-day rows carry
calendar features plus activity levels measured strictly *before* the origin;
no target transaction, count or amount enters a feature row.

Sampling draws whole equally weighted scenarios: every generated event is kept
as its own row, ``EventPaths.daily()`` reconciles counts and amounts exactly,
zero-event scenarios and multiple same-day events are ordinary outcomes, and
only genuinely unique obligations may carry ``known_event_id`` (the case data
has no invoice labels, so this generator always emits an empty id).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import lightgbm as lgb

from zavozik_ml.event_forecasters.core import (
    ConditionalAmounts,
    EventHistory,
    EventPaths,
    FitOptions,
    available_marks,
    calendar_features,
)

DIRECTIONS = (0, 1)
_DIRECTION_NAME = {0: "in", 1: "out"}

WARMUP_DAYS = 28  # observed days needed before a training row is eligible
LEVEL_WINDOWS = (28, 91)  # activity-level lookbacks, in observed days
RECENT_MARK_DAYS = 182  # sampling-history marks used for local smoothing
BLOCK_LOOKBACK_DAYS = 364  # only recent observed days may supply a regime block
MIN_BLOCK_POSITIVE = 2  # positive amounts per direction for a usable block factor
REGIME_BOUNDS = (0.25, 4.0)  # explicit clip on the historical block factor
MONTH_BUCKETS = 3  # days 1-10 / 11-20 / 21-end
MARK_PRIOR_COMPANY = 8.0  # pseudo-events shrinking company marks to the pool
MARK_PROB_FLOOR = 1e-3  # keeps rare marks reachable
DISPERSION_BOUNDS = (1.0, 200.0)  # 1.0 is the documented geometric fallback
LAMBDA_CAP = 64.0  # explicit cap on a single negative-binomial rate
HOLDOUT_SHARE = 0.3  # latest share of eligible days, used only to size overdispersion
MIN_HOLDOUT_ROWS = 40
MIN_ROWS_PER_COMPANY = 60  # a training-row cap never starves a single company

HURDLE_PARAMS = dict(
    objective="binary",
    learning_rate=0.05,
    num_leaves=15,
    min_data_in_leaf=20,
    feature_fraction=0.8,
    bagging_fraction=0.8,
    bagging_freq=1,
    lambda_l2=1.0,
    force_col_wise=True,
    verbose=-1,
)
POSITIVE_PARAMS = dict(HURDLE_PARAMS, objective="poisson")


def _month_bucket(day_of_month):
    """Coarse position-in-month; separates rent-style and month-end streams."""
    return np.minimum((np.asarray(day_of_month, dtype=int) - 1) // 10, MONTH_BUCKETS - 1)


def _activity_arrays(history: EventHistory):
    """Per-day company activity and exposure, index ``i`` using days before ``i``.

    Arrays have length ``len(dates) + 1`` so index ``len(dates)`` describes the
    origin itself, which is what sampling needs. Unknown days contribute no
    count and no exposure denominator, so a gap can never read as observed
    silence.
    """
    counts = np.nan_to_num(history.daily_counts, nan=0.0)
    known = np.asarray(history.known, dtype=float)
    n = len(known)
    index = np.arange(n + 1)
    cum_count = np.concatenate([np.zeros((1, 2)), np.cumsum(counts, axis=0)])
    cum_positive = np.concatenate([np.zeros((1, 2)), np.cumsum(counts > 0, axis=0)])
    cum_known = np.concatenate([[0.0], np.cumsum(known)])
    features = {}
    for window in LEVEL_WINDOWS:
        low = np.maximum(0, index - window)
        seen = np.maximum(cum_known[index] - cum_known[low], 0.0)
        for direction in DIRECTIONS:
            name = _DIRECTION_NAME[direction]
            events = np.maximum(cum_count[index, direction] - cum_count[low, direction], 0.0)
            active = np.maximum(cum_positive[index, direction] - cum_positive[low, direction], 0.0)
            features[f"rate_{window}_{name}"] = events / np.maximum(seen, 1.0)
            features[f"pos_share_{window}_{name}"] = active / np.maximum(seen, 1.0)
            features[f"mean_pos_{window}_{name}"] = events / np.maximum(active, 1.0)
    warm = np.maximum(0, index - WARMUP_DAYS)
    exposure = np.maximum(cum_known[index] - cum_known[warm], 0.0)
    return features, exposure


def _feature_frame(targets, activity):
    """Target-day calendar plus origin-visible activity; never the target facts.

    The calendar block is target-day only, so a per-day hurdle needs no horizon
    index; ``calendar_features`` also emits a constant ``workdays_ahead`` column
    (it is called with the target as its own origin), which carries no fit
    information and is dropped.
    """
    frame = calendar_features(targets).drop(columns=["workdays_ahead"])
    for name, values in activity.items():
        frame[name] = np.asarray(values, dtype=np.float32)
    return frame


def _training_frame(histories, max_training_rows):
    """Eligible (origin, target) rows from complete days, newest rows first."""
    per_company = max(MIN_ROWS_PER_COMPANY, int(max_training_rows) // max(len(histories), 1))
    frames, labels, splits = [], {direction: [] for direction in DIRECTIONS}, []
    for history in histories:
        activity, exposure = _activity_arrays(history)
        known = np.asarray(history.known, dtype=bool)
        eligible = known & (exposure[:len(known)] >= WARMUP_DAYS)
        days = np.flatnonzero(eligible)[-per_company:]
        if not len(days):
            continue
        frames.append(_feature_frame(history.dates[days],
                                     {name: values[days] for name, values in activity.items()}))
        counts = np.nan_to_num(history.daily_counts, nan=0.0)
        for direction in DIRECTIONS:
            labels[direction].append(counts[days, direction])
        held = np.zeros(len(days), dtype=bool)
        held[-max(1, int(round(HOLDOUT_SHARE * len(days)))):] = True
        splits.append(held)
    if not frames:
        return None, None, None
    features = pd.concat(frames, ignore_index=True)
    return (features, {direction: np.concatenate(rows) for direction, rows in labels.items()},
            np.concatenate(splits))


def _mark_pools(histories, marks):
    """Event shares per (scope, direction, month bucket) scope over ``marks``."""
    order = {mark: i for i, mark in enumerate(marks)}
    raw = {}

    def add(key, ids):
        counts = raw.setdefault(key, np.zeros(len(marks)))
        if len(ids):
            np.add.at(counts, ids, 1.0)

    for history in histories:
        events = history.events
        if not len(events):
            continue
        ids = events.category.astype(str).map(order).to_numpy()
        directions = events.direction.to_numpy(int)
        buckets = _month_bucket(events.date.dt.day.to_numpy())
        for scope in ("*", history.industry):
            add((scope, None, None), ids)
            for direction in DIRECTIONS:
                of_direction = directions == direction
                add((scope, direction, None), ids[of_direction])
                for bucket in range(MONTH_BUCKETS):
                    add((scope, direction, bucket), ids[of_direction & (buckets == bucket)])
    pools = {}
    for key, counts in raw.items():
        total = counts.sum()
        if total <= 0:
            continue
        shares = counts / total
        pools[key] = (shares + MARK_PROB_FLOOR) / (1.0 + len(shares) * MARK_PROB_FLOOR)
    return pools


def _fit_booster(params, features, labels, options):
    dataset = lgb.Dataset(features, label=np.asarray(labels, dtype=float), free_raw_data=True)
    seed = int(options.seed)
    return lgb.train(
        dict(params, seed=seed, num_threads=max(1, int(options.threads)),
             bagging_seed=seed + 1, feature_fraction_seed=seed + 3, data_random_seed=seed + 5),
        dataset, num_boost_round=max(1, int(options.rounds)))


class Model:
    """Hurdle counts with smoothed marks and a shared historical activity regime."""

    def __init__(self, options: FitOptions | None = None):
        self.options = options or FitOptions()
        self.marks_ = ["unknown"]
        self.mark_pools_ = {}
        self.amounts_ = ConditionalAmounts()
        self.feature_columns_ = []
        self.hurdle_ = {}
        self.positive_ = {}
        self.dispersion_ = {}
        self.dispersion_method_ = {}
        self.dispersion_clipped_ = {}
        self.fit_diagnostics_ = {}

    # ------------------------------------------------------------------ fit
    def fit(self, histories):
        histories = list(histories)
        self.marks_ = available_marks(histories)
        self.mark_pools_ = _mark_pools(histories, self.marks_)
        self.amounts_ = ConditionalAmounts().fit(histories)
        features, labels, held = _training_frame(histories, self.options.max_training_rows)
        self.hurdle_, self.positive_ = {}, {}
        self.dispersion_, self.dispersion_method_, self.dispersion_clipped_ = {}, {}, {}
        if features is None:
            self.feature_columns_ = []
            self.fit_diagnostics_ = self._fit_diagnostics(histories, 0, 0)
            return self
        self.feature_columns_ = list(features.columns)
        matrix = features.to_numpy(np.float32)
        positives = 0
        for direction in DIRECTIONS:
            counts = labels[direction]
            positive = counts >= 1
            positives += int(positive.sum())
            self.dispersion_[direction], self.dispersion_method_[direction], \
                self.dispersion_clipped_[direction] = self._estimate_dispersion(
                    matrix, counts, positive, held)
            self.hurdle_[direction] = _fit_booster(
                HURDLE_PARAMS, matrix, (counts >= 1).astype(float), self.options)
            # A degenerate positive law (every active day holds exactly one event)
            # needs no booster: the Poisson mean is zero by construction.
            self.positive_[direction] = _fit_booster(
                POSITIVE_PARAMS, matrix[positive], counts[positive] - 1.0, self.options) \
                if int(positive.sum()) and float(np.sum(counts[positive] - 1.0)) > 0.0 else None
        self.fit_diagnostics_ = self._fit_diagnostics(histories, len(matrix), positives)
        return self

    def _estimate_dispersion(self, matrix, counts, positive, held):
        """Method of moments on days held out from the positive-count fit."""
        early, late = positive & ~held, positive & held
        if int(early.sum()) < MIN_HOLDOUT_ROWS or int(late.sum()) < MIN_HOLDOUT_ROWS:
            return 1.0, "geometric_fallback", False
        excess = counts[late] - 1.0
        if float(np.sum(counts[early] - 1.0)) <= 0.0:
            return DISPERSION_BOUNDS[1], "underdispersed_upper_bound", True
        probe = _fit_booster(POSITIVE_PARAMS, matrix[early], counts[early] - 1.0, self.options)
        mean = np.maximum(probe.predict(matrix[late]), 0.0)
        numerator = float(np.sum(mean ** 2))
        denominator = float(np.sum((excess - mean) ** 2)) - float(np.sum(mean))
        if numerator <= 0.0:
            return 1.0, "geometric_fallback", False
        if denominator <= 0.0:
            return DISPERSION_BOUNDS[1], "underdispersed_upper_bound", True
        shape = numerator / denominator
        clipped = not (DISPERSION_BOUNDS[0] <= shape <= DISPERSION_BOUNDS[1])
        return float(np.clip(shape, *DISPERSION_BOUNDS)), "heldout_method_of_moments", clipped

    def _fit_diagnostics(self, histories, rows, positive_rows):
        observed = {direction: 0 for direction in DIRECTIONS}
        for history in histories:
            events = history.events
            for direction in DIRECTIONS:
                observed[direction] += int((events.direction == direction).sum())
        return {
            "model": "marked_counts",
            "companies": len(histories),
            "training_rows": int(rows),
            "positive_rows": int(positive_rows),
            "max_training_rows": int(self.options.max_training_rows),
            "marks": len(self.marks_),
            "mark_pools": len(self.mark_pools_),
            "observed_events": {_DIRECTION_NAME[d]: observed[d] for d in DIRECTIONS},
            "count_cap": int(self.options.max_events_per_day),
            "dispersion": {_DIRECTION_NAME[d]: float(self.dispersion_.get(d, 1.0))
                           for d in DIRECTIONS},
            "dispersion_method": {_DIRECTION_NAME[d]: self.dispersion_method_.get(d, "none")
                                  for d in DIRECTIONS},
            "dispersion_clipped": {_DIRECTION_NAME[d]: bool(self.dispersion_clipped_.get(d, False))
                                   for d in DIRECTIONS},
        }

    # --------------------------------------------------------------- sample
    def sample(self, history: EventHistory, horizon: int, n_paths: int, rng):
        horizon, n_paths = int(horizon), int(n_paths)
        if horizon < 1 or n_paths < 1:
            raise ValueError("positive horizon and path count required")
        target = np.asarray(history.as_of, dtype="datetime64[D]") \
            + np.arange(1, horizon + 1).astype("timedelta64[D]")
        allowed = np.asarray(history.allowed(target), dtype=bool)
        activity, _ = _activity_arrays(history)
        origin_row = len(history.dates)
        frame = _feature_frame(target, {name: values[origin_row]
                                        for name, values in activity.items()})
        matrix = np.tile(frame.to_numpy(np.float32), (n_paths, 1))
        allowed_flat = np.tile(allowed, n_paths)

        draws, lambda_clipped = self._draw_counts(history, matrix, allowed_flat, rng)
        draws, clip = self._apply_count_cap(draws)
        clip["lambda_cap_draws"] = lambda_clipped

        paths, days, directions = self._expand(draws, horizon)
        total = len(paths)
        diagnostics = dict(self.fit_diagnostics_)
        diagnostics.update(horizon=horizon, n_paths=n_paths, events=int(total),
                           allowed_days=int(allowed.sum()),
                           disallowed_days=int((~allowed).sum()),
                           clipping=clip, zero_amount_events=0, invalid_amount_events=0)
        if not total:
            diagnostics.update(activity_regime="no_events", regime_blocks=0,
                               regime_clipped_blocks=0)
            return EventPaths.from_records(history, horizon, n_paths, [], diagnostics)

        categories = self._draw_categories(history, target, days, directions, rng)
        amounts, zero_amounts, invalid = self._draw_amounts(history, days, directions,
                                                            categories, rng)
        factors, regime = self._regime_factors(history, horizon, n_paths, rng)
        amounts = amounts * factors[directions, paths]
        amounts = np.round(np.where(np.isfinite(amounts), np.maximum(amounts, 0.0), 0.0), 2)
        diagnostics.update(regime)
        diagnostics["zero_amount_events"] = int(zero_amounts)
        diagnostics["invalid_amount_events"] = int(invalid)

        order = np.lexsort((directions, days, paths))
        records = pd.DataFrame({
            "path": np.asarray(paths, dtype=int)[order],
            "day": np.asarray(days, dtype=int)[order],
            "direction": np.asarray(directions, dtype=int)[order],
            "amount": amounts[order],
            "category": np.asarray(categories, dtype=object)[order],
            "counterparty": "",
            "known_event_id": "",
        })
        return EventPaths.from_records(history, horizon, n_paths,
                                       records.to_dict("records"), diagnostics)

    def _draw_counts(self, history, matrix, allowed_flat, rng):
        """Independent hurdle draws per direction and day, then a documented cap."""
        rows = matrix.shape[0]
        draws = np.zeros((2, rows))
        lambda_clipped = 0
        for direction in DIRECTIONS:
            chance, mean, shape = self._count_parameters(history, direction, matrix)
            active = rng.random(rows) < chance
            rate = np.maximum(mean, 0.0) / shape
            spread = rng.gamma(shape=shape, scale=rate)
            lambda_clipped += int((active & (spread > LAMBDA_CAP)).sum())
            excess = rng.poisson(np.minimum(spread, LAMBDA_CAP))
            counts = np.where(active, 1.0 + excess, 0.0)
            counts[~allowed_flat] = 0.0
            draws[direction] = counts
        return draws, lambda_clipped

    def _count_parameters(self, history, direction, matrix):
        booster, positive = self.hurdle_.get(direction), self.positive_.get(direction)
        shape = self.dispersion_.get(direction, 1.0)
        rows = matrix.shape[0]
        if booster is not None:
            chance = np.clip(booster.predict(matrix), 0.0, 1.0)
            mean = np.maximum(positive.predict(matrix), 0.0) if positive is not None \
                else np.zeros(rows)
            return chance, mean, shape
        # No fitted row at all: pooled visible-day rates, geometric positive law.
        # Rates are per admissible day, matching how sampling masks forbidden days.
        counts = history.daily_counts
        known = np.asarray(history.known, dtype=bool)
        allowed = np.asarray(history.allowed(history.dates), dtype=bool)
        visible = np.nan_to_num(counts[known & allowed, direction], nan=0.0)
        if not len(visible) or visible.max() <= 0:
            return np.zeros(rows), np.zeros(rows), 1.0
        return (np.full(rows, float((visible > 0).mean())),
                np.full(rows, max(float(visible[visible > 0].mean()) - 1.0, 0.0)), 1.0)

    def _apply_count_cap(self, draws):
        """Proportional trim of any (scenario, day) above the explicit cap."""
        cap = max(1, int(self.options.max_events_per_day))
        total = draws.sum(axis=0)
        over = total > cap
        clip = {"count_cap_rows": int(over.sum()), "count_cap_events": 0, "lambda_cap_draws": 0}
        if over.any():
            trimmed = np.floor(draws[:, over] * (cap / total[over]))
            clip["count_cap_events"] = int((total[over] - trimmed.sum(axis=0)).sum())
            draws[:, over] = trimmed
        return draws, clip

    @staticmethod
    def _expand(draws, horizon):
        paths, days, directions = [], [], []
        for direction in DIRECTIONS:
            index = np.flatnonzero(draws[direction] >= 1.0)
            if not len(index):
                continue
            repeats = draws[direction][index].astype(int)
            paths.append(np.repeat(index // horizon, repeats))
            days.append(np.repeat(index % horizon + 1, repeats))
            directions.append(np.full(int(repeats.sum()), direction, dtype=int))
        if not paths:
            empty = np.empty(0, dtype=int)
            return empty, empty, empty
        return np.concatenate(paths), np.concatenate(days), np.concatenate(directions)

    def _base_mark_shares(self, history, direction, bucket):
        for key in ((history.industry, direction, bucket),
                    ("*", direction, bucket),
                    (history.industry, direction, None),
                    ("*", direction, None),
                    (history.industry, None, None),
                    ("*", None, None)):
            shares = self.mark_pools_.get(key)
            if shares is not None:
                return shares
        return None

    def _mark_distribution(self, history, direction, bucket):
        """Company-visible shares shrunk to the fitted hierarchical pool."""
        events = history.events
        recent = events[(events.direction == direction) &
                        (events.date >= pd.Timestamp(history.as_of
                                                     - np.timedelta64(RECENT_MARK_DAYS, "D")))]
        observed = {str(mark) for mark in recent.category}
        marks = list(self.marks_) + sorted(observed - set(self.marks_))
        counts = np.zeros(len(marks))
        if len(recent):
            order = {mark: i for i, mark in enumerate(marks)}
            np.add.at(counts, recent.category.astype(str).map(order).to_numpy(), 1.0)
        base = self._base_mark_shares(history, direction, bucket)
        shares = np.zeros(len(marks))
        if base is not None:
            shares[:len(self.marks_)] = base
        if shares.sum() <= 0.0 and counts.sum() <= 0.0:
            return marks, np.full(len(marks), 1.0 / len(marks))
        shares = shares / max(shares.sum(), 1e-12)
        prior = MARK_PRIOR_COMPANY
        shares = (counts + prior * shares) / (counts.sum() + prior)
        shares = np.asarray(shares, dtype=float)
        return marks, shares / shares.sum()

    def _draw_categories(self, history, target, days, directions, rng):
        bucket_of_day = _month_bucket(pd.DatetimeIndex(target).day.to_numpy())[days - 1]
        categories = np.empty(len(days), dtype=object)
        for direction in DIRECTIONS:
            in_direction = np.flatnonzero(directions == direction)
            if not len(in_direction):
                continue
            for bucket in range(MONTH_BUCKETS):
                chosen = in_direction[bucket_of_day[in_direction] == bucket]
                if not len(chosen):
                    continue
                marks, shares = self._mark_distribution(history, direction, bucket)
                picks = rng.choice(len(marks), size=len(chosen), p=shares)
                categories[chosen] = np.asarray(marks, dtype=object)[picks]
        return categories

    def _draw_amounts(self, history, days, directions, categories, rng):
        """Pooled draws conditioned on direction, mark and company scale."""
        amounts = np.zeros(len(days))
        invalid = 0
        for direction in DIRECTIONS:
            in_direction = directions == direction
            if not in_direction.any():
                continue
            marks = np.unique(categories[in_direction].astype(str))
            for mark in marks:
                chosen = np.flatnonzero(in_direction & (categories == mark))
                drawn = np.asarray(self.amounts_.sample(history, int(direction), str(mark),
                                                        len(chosen), rng), dtype=float)
                bad = ~np.isfinite(drawn)
                invalid += int(bad.sum())
                amounts[chosen] = np.where(bad, 0.0, np.maximum(drawn, 0.0))
        return amounts, int((amounts <= 0.0).sum()), invalid

    def _regime_factors(self, history, horizon, n_paths, rng):
        """One historical activity block per scenario, shared by both directions."""
        facts = dict(activity_regime="insufficient_history", regime_blocks=0,
                     regime_clipped_blocks=0)
        factors = np.ones((2, n_paths))
        known = np.asarray(history.known, dtype=bool)
        n = len(known)
        events = history.events
        if n <= horizon or not len(events):
            return factors, facts
        day = (events.date.to_numpy(dtype="datetime64[D]") - history.dates[0]).astype(int)
        direction = events.direction.to_numpy(int)
        amount = events.amount.to_numpy(float)
        positive = amount > 0.0
        daily_positive = np.zeros((n, 2))
        daily_amount = np.zeros((n, 2))
        np.add.at(daily_positive, (day[positive], direction[positive]), 1.0)
        np.add.at(daily_amount, (day[positive], direction[positive]), amount[positive])

        coverage = np.convolve(known.astype(int), np.ones(horizon, dtype=int), mode="valid")
        starts = np.flatnonzero(coverage == horizon)
        starts = starts[starts >= max(0, n - BLOCK_LOOKBACK_DAYS)]
        if not len(starts):
            return factors, facts

        cum_positive = np.concatenate([np.zeros((1, 2)), np.cumsum(daily_positive, axis=0)])
        cum_amount = np.concatenate([np.zeros((1, 2)), np.cumsum(daily_amount, axis=0)])
        block_positive = cum_positive[starts + horizon] - cum_positive[starts]
        block_amount = cum_amount[starts + horizon] - cum_amount[starts]

        picked = rng.integers(len(starts), size=n_paths)
        clips = 0
        for direction in DIRECTIONS:
            observed_count = float(daily_positive[known, direction].sum())
            baseline = float(daily_amount[known, direction].sum()) / max(observed_count, 1.0)
            if baseline <= 0.0:
                continue
            usable = block_positive[:, direction] >= MIN_BLOCK_POSITIVE
            raw = np.ones(len(starts))
            raw[usable] = (block_amount[usable, direction] / block_positive[usable, direction]) \
                / baseline
            clips += int((usable & ((raw < REGIME_BOUNDS[0]) | (raw > REGIME_BOUNDS[1]))).sum())
            factors[direction] = np.clip(raw, *REGIME_BOUNDS)[picked]
        facts.update(activity_regime="historical_blocks", regime_blocks=int(len(starts)),
                     regime_clipped_blocks=clips)
        return factors, facts

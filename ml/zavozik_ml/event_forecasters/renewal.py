"""Research-only discrete-day renewal (activation hazard) event generator.

Lane: renewal. Not registered for serving; the joint law is a modelling choice,
not a calibrated description of any company.

Design, i.e. the assumptions this lane is allowed to make:
  * Streams are pooled ``(direction, category)`` pairs. Only the leading
    ``MAX_STREAMS`` by observed active days are generated; streams below
    ``MIN_STREAM_DAYS`` observed active days, and the tail beyond the cap, are
    dropped and reported in ``self.diagnostics``. Thin streams therefore borrow
    strength from the pooled hazard rather than getting their own dynamics.
  * Activation: ``P(>=1 event of stream s on day d)`` from a shallow LightGBM
    binary model over calendar terms, the elapsed days since that stream's last
    *observed* event (renewal age), whether that age is exact, and origin-prefix
    activity. Missing exposure makes the age unknown until a new event reanchors
    it: gaps are never read as long observed silences.
  * Multiplicity: the empirical count law of the stream's observed active days,
    pooled when a stream is thin, truncated at ``FitOptions.max_events_per_day``.
  * Amounts: ``core.ConditionalAmounts`` pools fitted on the supplied prefixes;
    local donors are only the events visible at sampling time.
  * Dependence: one persistent activity regime per scenario path, drawn from the
    empirical marginal of trailing total activity, shifts every stream's
    activation odds by a fitted log-odds term. This couples streams within a
    path but is a heuristic, not an estimated dynamic factor model.
  * No counterparty or invoice identifier is invented: ``counterparty`` and
    ``known_event_id`` stay empty unless a stream carries a real obligation,
    which canonical case data does not.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .core import ConditionalAmounts, EventHistory, EventPaths, FitOptions, calendar_features

try:  # LightGBM is the research default; the pooled table hazard needs no extra deps.
    import lightgbm
except ImportError:  # pragma: no cover - surfaced through diagnostics
    lightgbm = None

CAL_COLUMNS = ("weekday", "day", "month", "days_to_eom", "is_workday", "off_before",
               "wd_of_month", "wd_to_eom", "is_tax_day", "is_pay10", "is_pay25")
ROW_COLUMNS = ("log_age", "age_known", "active_30", "known_30", "rate_30", "rate_90")

MAX_STREAMS = 16        # explicit stream cap; wider pools need more evidence
MIN_STREAM_DAYS = 3     # observed active days required to treat a stream as fitted
WARMUP_DAYS = 28        # trailing activity needs some observed prefix
TRAIL_SHORT = 30
TRAIL_LONG = 90
AGE_EDGES = (2, 4, 9, 16, 32, 62, 122)
AGE_UNKNOWN = len(AGE_EDGES) + 1
HAZARD_CEILING = 0.98   # never emit near-certain activations
REGIME_EDGES = (0.34, 0.67)
REGIME_THETA_LIMIT = 1.5
LAPLACE_ROWS = 4.0
LAPLACE_STREAM = 8.0
AMOUNT_BLOCK = 64


def _logit(p):
    p = np.clip(np.asarray(p, dtype=np.float64), 1e-6, 1.0 - 1e-6)
    return np.log(p) - np.log1p(-p)


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=np.float64)))


def _scalar_logit(p):
    p = min(max(float(p), 1e-4), 1.0 - 1e-4)
    return math.log(p / (1.0 - p))


def _age_bucket(age, age_known):
    bucket = np.searchsorted(np.asarray(AGE_EDGES), np.asarray(age, dtype=np.float64), side="right")
    bucket = np.minimum(bucket, AGE_UNKNOWN - 1)
    return np.where(np.asarray(age_known, dtype=bool), bucket, AGE_UNKNOWN)


def _stream_counts(history, streams):
    """Per-day, per-stream observed event counts on complete days only."""
    dates = np.asarray(history.dates, dtype="datetime64[D]")
    counts = np.zeros((len(dates), len(streams)), dtype=np.int32)
    events = history.events
    if len(events) and streams:
        index = {stream: k for k, stream in enumerate(streams)}
        day = (events.date.to_numpy(dtype="datetime64[D]") - dates[0]).astype(int)
        column = np.fromiter(
            (index.get((int(d), str(c)), -1)
             for d, c in zip(events.direction.to_numpy(int), events.category.to_numpy())),
            dtype=int, count=len(events))
        keep = column >= 0
        np.add.at(counts, (day[keep], column[keep]), 1)
    return counts


def _select_streams(histories, limit=MAX_STREAMS):
    """Rank pooled (direction, category) streams by observed active days."""
    observed = {}
    for history in histories:
        events = history.events
        if not len(events):
            continue
        grouped = events.groupby(["direction", "category"], observed=True)
        for (direction, category), group in grouped:
            key = (int(direction), str(category))
            days, count = observed.get(key, (0, 0))
            observed[key] = (days + int(group.date.nunique()), count + int(len(group)))
    fitted = [key for key, (days, _) in observed.items() if days >= MIN_STREAM_DAYS]
    fitted.sort(key=lambda key: (-observed[key][0], -observed[key][1], key))
    streams = fitted[:limit]
    dropped = {key: observed[key] for key in observed if key not in set(streams)}
    return streams, dropped


def _activation_rows(history, streams):
    """Origin-visible activation rows: renewal age plus trailing activity per day.

    Rows use only complete days known at this cutoff and never the target day's
    own events. ``keep`` marks the days that may become training targets.
    """
    dates = np.asarray(history.dates, dtype="datetime64[D]")
    days = len(dates)
    known = np.asarray(history.known, dtype=bool)
    allowed = np.asarray(history.allowed(dates), dtype=bool)
    index = np.arange(days)
    counts = _stream_counts(history, streams)
    active = counts > 0

    unknown_cum = np.concatenate([[0.0], np.cumsum(~known, dtype=np.float64)])
    age = np.zeros((days, len(streams)), dtype=np.float64)
    age_known = np.zeros((days, len(streams)), dtype=bool)
    for s in range(len(streams)):
        last = np.maximum.accumulate(np.where(active[:, s], index, -1))
        previous = np.concatenate([[-1], last[:-1]])  # own event is never a feature
        age[:, s] = np.where(previous >= 0, index - previous, index + 1)
        # Unknown days strictly after the last observed event make the age a lower bound.
        since = np.where(previous >= 0, unknown_cum[np.clip(previous + 1, 0, days)], 0.0)
        age_known[:, s] = (unknown_cum[index + 1] - since) == 0.0

    active_cum = np.concatenate([np.zeros((1, len(streams))),
                                 np.cumsum(active & known[:, None], axis=0)])
    known_cum = np.concatenate([[0.0], np.cumsum(known, dtype=np.float64)])
    any_active = active.any(axis=1)
    any_cum = np.concatenate([[0.0], np.cumsum(any_active & known, dtype=np.float64)])

    def trailing(cum, window):
        low = np.maximum(index - window, 0)
        return cum[index] - cum[low]

    active_30 = trailing(active_cum, TRAIL_SHORT)
    known_30 = np.repeat(trailing(known_cum, TRAIL_SHORT)[:, None], len(streams), axis=1)
    rate_30 = np.divide(active_30, known_30, out=np.zeros_like(active_30), where=known_30 > 0)
    known_long = trailing(known_cum, TRAIL_LONG)
    any_long = trailing(any_cum, TRAIL_LONG)
    rate_90 = np.divide(any_long, known_long, out=np.zeros(days), where=known_long > 0)

    keep = known & allowed
    keep[:min(WARMUP_DAYS, days)] = False
    return dict(dates=dates, counts=counts, active=active, age=age, age_known=age_known,
                active_30=active_30, known_30=known_30, rate_30=rate_30, rate_90=rate_90,
                keep=keep)


def _design(cal_rows, stream_codes, age, age_known, active_30, known_30, rate_30, rate_90, n_streams):
    """Assemble the activation design matrix shared by fitting and generation."""
    frame = pd.DataFrame()
    for j, name in enumerate(CAL_COLUMNS):
        frame[name] = np.asarray(cal_rows[:, j], dtype=np.float32)
    frame["log_age"] = np.log1p(np.asarray(age, dtype=np.float64)).astype(np.float32)
    frame["age_known"] = np.asarray(age_known, dtype=np.float32)
    frame["active_30"] = np.asarray(active_30, dtype=np.float32)
    frame["known_30"] = np.asarray(known_30, dtype=np.float32)
    frame["rate_30"] = np.asarray(rate_30, dtype=np.float32)
    frame["rate_90"] = np.asarray(rate_90, dtype=np.float32)
    codes = np.asarray(stream_codes)
    for k in range(n_streams):
        frame[f"stream_{k}"] = (codes == k).astype(np.float32)
    return frame


def _feature_names(n_streams):
    return [*CAL_COLUMNS, *ROW_COLUMNS, *[f"stream_{k}" for k in range(n_streams)]]


class _TableHazard:
    """Laplace-smoothed pooled activation rates over (stream, renewal-age bucket).

    Statistical fallback for trees: an empirical hazard table with hierarchical
    smoothing (cell -> stream -> global), no external dependency.
    """

    def __init__(self, n_streams):
        self.n_streams = n_streams
        self.global_rate = 0.0
        self.grid = np.zeros((n_streams, AGE_UNKNOWN + 1))

    def fit(self, stream_codes, age, age_known, labels):
        codes = np.asarray(stream_codes, dtype=int)
        bucket = _age_bucket(age, age_known)
        width = AGE_UNKNOWN + 1
        flat = codes * width + bucket
        size = self.n_streams * width
        hits = np.bincount(flat, weights=np.asarray(labels, dtype=np.float64), minlength=size)
        total = np.bincount(flat, minlength=size).astype(np.float64)
        stream_hits = np.bincount(codes, weights=np.asarray(labels, dtype=np.float64),
                                  minlength=self.n_streams)
        stream_total = np.bincount(codes, minlength=self.n_streams).astype(np.float64)
        self.global_rate = float((hits.sum() + 0.5) / (total.sum() + 1.0))
        stream_rate = (stream_hits + LAPLACE_STREAM * self.global_rate) / (stream_total + LAPLACE_STREAM)
        prior = np.repeat(stream_rate, width)
        smoothed = (hits + LAPLACE_ROWS * prior) / (total + LAPLACE_ROWS)
        self.grid = smoothed.reshape(self.n_streams, width)
        return self

    def predict(self, stream_codes, age, age_known):
        codes = np.asarray(stream_codes, dtype=int)
        return self.grid[codes, _age_bucket(age, age_known)]


class Model:
    """Pooled discrete-day renewal generator; see the module docstring for assumptions.

    ``fit`` takes the fit prefixes only (no calibration or test data) and reads
    their complete observed days; ``sample`` reads the same information at the
    sampling cutoff, so facts beyond ``history.as_of`` never influence a path.
    """

    def __init__(self, options: FitOptions | None = None):
        self.options = options or FitOptions()
        self.streams: list[tuple[int, str]] = []
        self.hazard_kind = "unfitted"
        self.booster = None
        self.table: _TableHazard | None = None
        self.feature_names: list[str] = []
        self.multiplicity: list[np.ndarray] = []
        self.multiplicity_pooled = np.array([1])
        self.regime_probs = np.ones(1)
        self.regime_theta = np.zeros(1)
        self.amounts: ConditionalAmounts | None = None
        self.amount_scale: dict[int, float] = {}
        self.diagnostics: dict = {}

    # ---------------------------------------------------------------- fitting
    def fit(self, histories: list[EventHistory]) -> "Model":
        histories = list(histories)
        options = self.options
        streams, dropped = _select_streams(histories, MAX_STREAMS)
        self.streams = streams
        self.amounts = ConditionalAmounts().fit(histories)
        self.amount_scale = _fit_amount_scale(histories)

        self._fit_multiplicity(histories, streams)
        rows = self._training_matrix(histories, streams)

        if not streams or rows is None:
            self.hazard_kind = "empty"
            self.booster, self.table = None, None
            self.regime_probs = np.ones(1)
            self.regime_theta = np.zeros(1)
            self.feature_names = _feature_names(len(streams))
            self.diagnostics = {
                "streams": [f"{d}:{c}" for d, c in streams],
                "dropped_streams": [f"{d}:{c}" for d, c in sorted(dropped)],
                "training_rows": 0, "hazard_kind": "empty",
                "notes": ["no usable fit exposure; generator returns empty scenarios"],
            }
            return self

        frame, labels, stream_codes, age, age_known, rate_90 = rows
        self.regime_probs, self.regime_theta = self._fit_regime(rate_90, labels)
        self.feature_names = _feature_names(len(streams))

        if lightgbm is not None and options.rounds > 0:
            self._fit_lightgbm(frame, labels)
        else:
            self._fit_table(stream_codes, age, age_known, labels)

        self.diagnostics = {
            "streams": [f"{d}:{c}" for d, c in streams],
            "dropped_streams": [f"{d}:{c}" for d, c in sorted(dropped)],
            "dropped_events": int(sum(count for _, count in dropped.values())),
            "training_rows": int(len(labels)),
            "activation_rate": float(labels.mean()),
            "hazard_kind": self.hazard_kind,
            "regime_probs": [float(p) for p in self.regime_probs],
            "regime_theta": [float(t) for t in self.regime_theta],
            "multiplicity_pooled_size": int(len(self.multiplicity_pooled)),
            "amount_scale_fallback": {int(k): float(v) for k, v in sorted(self.amount_scale.items())},
            "notes": [
                "streams outside the fitted cap are not generated (thin stream limitation)",
                "renewal age is unknown across missing exposure until an event reanchors it",
                "regime coupling is a heuristic log-odds shift, not a calibrated factor model",
                "amounts fall back to the pooled company scale only when a direction has no positive visible amount",
            ],
        }
        return self

    def _fit_multiplicity(self, histories, streams):
        pools = [[] for _ in streams]
        for history in histories:
            counts = _stream_counts(history, streams)
            for s in range(len(streams)):
                active = counts[:, s] > 0
                if active.any():
                    pools[s].extend(counts[active, s].tolist())
        self.multiplicity = [np.asarray(pool, dtype=np.int64) for pool in pools]
        pooled = [value for pool in pools for value in pool]
        self.multiplicity_pooled = (np.asarray(pooled, dtype=np.int64) if pooled
                                    else np.array([1], dtype=np.int64))

    def _training_matrix(self, histories, streams):
        blocks = []
        for history in histories:
            rows = _activation_rows(history, streams)
            keep = rows["keep"]
            if not keep.any():
                continue
            n_streams = len(streams)
            k = int(keep.sum())
            cal = calendar_features(rows["dates"])[list(CAL_COLUMNS)].to_numpy(np.float32)[keep]
            blocks.append(dict(
                cal=np.repeat(cal, n_streams, axis=0),
                stream_codes=np.tile(np.arange(n_streams), k),
                age=rows["age"][keep].ravel(),
                age_known=rows["age_known"][keep].ravel(),
                active_30=rows["active_30"][keep].ravel(),
                known_30=rows["known_30"][keep].ravel(),
                rate_30=rows["rate_30"][keep].ravel(),
                rate_90=np.repeat(rows["rate_90"][keep], n_streams),
                labels=rows["active"][keep].ravel().astype(np.float32),
            ))
        if not blocks:
            return None
        merged = {key: np.concatenate([block[key] for block in blocks]) for key in blocks[0]}
        keep = np.arange(len(merged["labels"]))
        if len(keep) > self.options.max_training_rows:
            rng = np.random.default_rng(self.options.seed)
            keep = np.sort(rng.choice(len(keep), size=self.options.max_training_rows, replace=False))
        merged = {key: value[keep] for key, value in merged.items()}
        frame = _design(merged["cal"], merged["stream_codes"], merged["age"], merged["age_known"],
                        merged["active_30"], merged["known_30"], merged["rate_30"], merged["rate_90"],
                        len(streams))
        return (frame, merged["labels"], merged["stream_codes"], merged["age"],
                merged["age_known"], merged["rate_90"])

    @staticmethod
    def _fit_regime(rate_90, labels):
        """Marginal regime mixture from trailing total activity, with log-odds shifts."""
        buckets = len(REGIME_EDGES) + 1
        edges = np.quantile(np.asarray(rate_90, np.float64), REGIME_EDGES)
        bucket = np.searchsorted(edges, np.asarray(rate_90, np.float64), side="right")
        overall = float(np.mean(labels))
        base = _scalar_logit(overall)
        probs = np.zeros(buckets)
        theta = np.zeros(buckets)
        for z in range(buckets):
            mask = bucket == z
            probs[z] = float(mask.mean())
            theta[z] = float(np.clip(_scalar_logit(float(np.mean(labels[mask]))) - base
                                     if mask.any() else 0.0, -REGIME_THETA_LIMIT, REGIME_THETA_LIMIT))
        if probs.sum() <= 0:
            probs = np.ones(buckets) / buckets
        probs = probs / probs.sum()
        return probs, theta

    def _fit_lightgbm(self, frame, labels):
        options = self.options
        params = dict(objective="binary", learning_rate=0.05, num_leaves=15, min_data_in_leaf=40,
                      feature_fraction=0.9, bagging_fraction=0.9, bagging_freq=1, lambda_l2=1.0,
                      num_threads=options.threads, seed=options.seed, bagging_seed=options.seed,
                      feature_fraction_seed=options.seed, deterministic=True, force_row_wise=True,
                      verbose=-1)
        dataset = lightgbm.Dataset(frame, label=np.asarray(labels, np.float64),
                                   feature_name=self.feature_names, free_raw_data=True)
        self.booster = lightgbm.train(params, dataset, num_boost_round=max(int(options.rounds), 1))
        self.hazard_kind = "lightgbm"

    def _fit_table(self, stream_codes, age, age_known, labels):
        self.table = _TableHazard(len(self.streams)).fit(stream_codes, age, age_known, labels)
        self.booster = None
        self.hazard_kind = "table"

    def _predict(self, frame, stream_codes, age, age_known):
        if self.hazard_kind == "lightgbm":
            probability = np.asarray(self.booster.predict(frame), dtype=np.float64)
        else:
            probability = self.table.predict(stream_codes, age, age_known)
        return np.clip(probability, 1e-6, 1.0 - 1e-6)

    def _amount_factor(self, history, direction):
        """Company scale for a direction without positive visible amounts (thin fallback)."""
        events = history.events
        if len(events) and ((events.direction == direction) & (events.amount > 0)).any():
            return 1.0
        return float(self.amount_scale.get(direction, 1.0))

    # -------------------------------------------------------------- generation
    def sample(self, history: EventHistory, horizon: int, n_paths: int, rng: np.random.Generator):
        horizon, n_paths = int(horizon), int(n_paths)
        if horizon < 1 or n_paths < 1:
            raise ValueError("positive horizon and path count required")
        if self.amounts is None:
            raise RuntimeError("fit the renewal model before sampling")
        options = self.options
        streams = self.streams
        n_streams = len(streams)
        can_fire = self.hazard_kind in ("lightgbm", "table")
        dates = history.as_of + np.arange(1, horizon + 1) * np.timedelta64(1, "D")
        allowed = np.asarray(history.allowed(dates), dtype=bool)
        calendar_rows = np.ascontiguousarray(
            calendar_features(dates)[list(CAL_COLUMNS)].to_numpy(np.float32))

        state = _origin_state(history, streams)
        width = TRAIL_LONG + horizon + 1
        cumulative_active = np.zeros((n_streams, n_paths, width), dtype=np.float32)
        block = np.repeat(state["active"][:, None, :], n_paths, axis=1)
        cumulative_active[:, :, 1:TRAIL_LONG + 1] = np.cumsum(block, axis=2)
        known_series = np.concatenate([state["known"], np.ones(horizon, dtype=np.float32)])
        cumulative_known = np.concatenate([[0.0], np.cumsum(known_series)])
        cumulative_any = np.zeros((n_paths, width), dtype=np.float32)
        cumulative_any[:, :TRAIL_LONG + 1] = np.cumsum(
            np.concatenate([[0.0], state["any"]]))[None, :].astype(np.float32)

        last_rel = np.repeat(state["last_rel"][:, None], n_paths, axis=1)
        age_known = np.repeat(state["age_known"][:, None], n_paths, axis=1)
        regime = rng.choice(len(self.regime_probs), size=n_paths, p=self.regime_probs)
        theta = self.regime_theta[regime]
        stream_codes = np.repeat(np.arange(n_streams), n_paths)

        diagnostics = {
            "model": "renewal",
            "hazard_kind": self.hazard_kind,
            "streams": [f"{d}:{c}" for d, c in streams],
            "dropped_streams": self.diagnostics.get("dropped_streams", []),
            "dropped_events": self.diagnostics.get("dropped_events", 0),
            "horizon": horizon,
            "paths": n_paths,
            "hazard_clipped": 0,
            "multiplicity_clipped": 0,
            "amount_blocks": 0,
            "regime_probs": [float(p) for p in self.regime_probs],
            "notes": ["clipped activations are dropped and do not reanchor the renewal clock",
                      "one persistent regime per path couples streams heuristically"],
        }
        buffers: dict[int, np.ndarray] = {}
        scales = {direction: self._amount_factor(history, direction) for direction in (0, 1)}
        diagnostics["amount_scale_used"] = {int(k): float(v) for k, v in sorted(scales.items())}
        path_parts, day_parts, dir_parts, amount_parts, cat_parts = [], [], [], [], []

        for t in range(1, horizon + 1):
            column = TRAIL_LONG + t
            high = column - 1
            low_short = max(high - TRAIL_SHORT, 0)
            low_long = max(high - TRAIL_LONG, 0)
            active_30 = cumulative_active[:, :, high] - cumulative_active[:, :, low_short]
            known_30 = cumulative_known[high] - cumulative_known[low_short]
            known_90 = cumulative_known[high] - cumulative_known[low_long]
            rate_30 = active_30 / known_30 if known_30 > 0 else np.zeros((n_streams, n_paths), np.float32)
            any_90 = cumulative_any[:, high] - cumulative_any[:, low_long]
            rate_90 = any_90 / known_90 if known_90 > 0 else np.zeros(n_paths, np.float32)

            multiplicity = np.zeros((n_streams, n_paths), dtype=np.int64)
            if can_fire and allowed[t - 1]:
                age = (t - last_rel).astype(np.float64)
                frame = _design(np.tile(calendar_rows[t - 1], (n_streams * n_paths, 1)),
                                stream_codes, age.ravel(), age_known.ravel(),
                                active_30.ravel(), np.full(n_streams * n_paths, known_30),
                                rate_30.ravel(), np.tile(rate_90, n_streams), n_streams)
                probability = self._predict(frame, stream_codes, age.ravel(), age_known.ravel())
                odds = _sigmoid(_logit(probability) + np.tile(theta, n_streams))
                clipped = int(np.count_nonzero(odds > HAZARD_CEILING))
                diagnostics["hazard_clipped"] += clipped
                probability = np.clip(odds, 0.0, HAZARD_CEILING)
                fired = rng.random(probability.size) < probability
                fired = fired.reshape(n_streams, n_paths)

                remaining = np.full(n_paths, options.max_events_per_day, dtype=np.int64)
                for s in range(n_streams):
                    paths = np.flatnonzero(fired[s])
                    if not len(paths):
                        continue
                    pool = self.multiplicity[s] if len(self.multiplicity[s]) else self.multiplicity_pooled
                    draw = rng.choice(pool, size=len(paths)).astype(np.int64)
                    take = np.minimum(draw, remaining[paths])
                    diagnostics["multiplicity_clipped"] += int(np.count_nonzero(draw > take))
                    multiplicity[s, paths] = take
                    remaining[paths] -= take

            for s in range(n_streams):
                counts = multiplicity[s]
                if not counts.any():
                    continue
                paths = np.repeat(np.arange(n_paths), counts)
                needed = int(paths.size)
                buffer = buffers.get(s)
                while buffer is None or len(buffer) < needed:
                    extra = self.amounts.sample(history, streams[s][0], streams[s][1],
                                                max(needed, AMOUNT_BLOCK), rng)
                    diagnostics["amount_blocks"] += 1
                    buffer = extra if buffer is None else np.concatenate([buffer, extra])
                amounts, buffers[s] = buffer[:needed], buffer[needed:]
                path_parts.append(paths)
                day_parts.append(np.full(needed, t, dtype=np.int64))
                dir_parts.append(np.full(needed, streams[s][0], dtype=np.int64))
                amount_parts.append(np.asarray(amounts, dtype=np.float64) * scales[streams[s][0]])
                cat_parts.append(np.full(needed, streams[s][1], dtype=object))

            emitted = multiplicity > 0
            last_rel = np.where(emitted, t, last_rel)
            age_known = age_known | emitted
            cumulative_active[:, :, column] = (cumulative_active[:, :, column - 1]
                                              + emitted.astype(np.float32))
            cumulative_any[:, column] = (cumulative_any[:, column - 1]
                                         + emitted.any(axis=0).astype(np.float32))

        if path_parts:
            paths = np.concatenate(path_parts)
            frame = pd.DataFrame({
                "path": paths,
                "day": np.concatenate(day_parts),
                "direction": np.concatenate(dir_parts),
                "amount": np.concatenate(amount_parts),
                "category": np.concatenate(cat_parts),
                "counterparty": "",
                "known_event_id": "",
            })
        else:
            frame = pd.DataFrame({"path": [], "day": [], "direction": [], "amount": [],
                                  "category": []})

        diagnostics["events"] = int(len(frame))
        diagnostics["zero_event_paths"] = int(n_paths - (np.bincount(
            frame.path.to_numpy(int), minlength=n_paths) > 0).sum()) if len(frame) else n_paths
        return EventPaths.from_records(history, horizon, n_paths, frame.to_dict("records"), diagnostics)


def _fit_amount_scale(histories):
    """Pooled per-direction amount level, used only for companies without visible activity."""
    positive: dict[int, list[float]] = {}
    for history in histories:
        events = history.events
        if not len(events):
            continue
        for direction in (0, 1):
            values = events.loc[(events.direction == direction) & (events.amount > 0), "amount"]
            if len(values):
                positive.setdefault(direction, []).extend(values.to_numpy(float).tolist())
    return {direction: float(np.median(values)) for direction, values in positive.items()}


def _origin_state(history, streams):
    """Renewal age and trailing exposure visible at the sampling origin."""
    dates = np.asarray(history.dates, dtype="datetime64[D]")
    days = len(dates)
    known = np.asarray(history.known, dtype=bool)
    counts = _stream_counts(history, streams)
    active = counts > 0
    unknown_cum = np.concatenate([[0.0], np.cumsum(~known, dtype=np.float64)])

    window = min(days, TRAIL_LONG)
    active_block = np.zeros((len(streams), TRAIL_LONG), dtype=np.float32)
    active_block[:, TRAIL_LONG - window:] = active[days - window:].T
    known_block = np.zeros(TRAIL_LONG, dtype=np.float32)
    known_block[TRAIL_LONG - window:] = known[days - window:]
    any_block = np.zeros(TRAIL_LONG, dtype=np.float32)
    any_block[TRAIL_LONG - window:] = active[days - window:].any(axis=1)

    last_rel = np.zeros(len(streams), dtype=np.int64)
    age_known = np.zeros(len(streams), dtype=bool)
    for s in range(len(streams)):
        hit = np.flatnonzero(active[:, s])
        if len(hit):
            last = int(hit[-1])
            last_rel[s] = -(days - 1 - last)
            age_known[s] = (unknown_cum[days] - unknown_cum[last + 1]) == 0.0
        else:
            last_rel[s] = -days
            age_known[s] = unknown_cum[days] == 0.0
    return dict(active=active_block, known=known_block, any=any_block,
                last_rel=last_rel, age_known=age_known)

"""Small CPU PyTorch GRU over day-resolution event summaries (research only).

One step is one day. The recurrent state reads a permutation-invariant day
summary (exposure flag, counts, amounts, mark histogram, calendar) and decodes the
*next* day: a bounded count bucket, a direction allocation, a mark allocation per
direction and an amount-bin distribution per (direction, mark). Amount bins are
fit-only log1p quantiles of the fit-scale amount, bin 0 carries the exact
zero-amount mass, and values inside a bin come from fit-only donor values. Only
when a positive bin has no donors at all does the sampler fall back to the
empirical :class:`~zavozik_ml.event_forecasters.core.ConditionalAmounts` pools;
each fallback event is counted in the diagnostics. Every generated event is kept
and scenarios stay equally weighted.

Discipline shared with the contract:

* only ``EventHistory.events``/``known`` (complete days at the cutoff) are read;
  ``raw_events`` is never touched, so prefix reconstruction is the caller's job;
* a gap is not an observed silence: targets need observed exposure on both the
  input and the target day, so missing days drop out of the loss instead of
  becoming zero-count days;
* no-event days and the terminal history day are real targets;
* mark vocabulary, feature scales, amount bins/donors and amount pools are
  fit-only, unseen marks collapse to the explicit ``unknown`` slot, and no
  counterparty or ``known_event_id`` is ever fabricated.

Torch is imported by this module only, never from the package ``__init__``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .core import (
    ConditionalAmounts,
    EventHistory,
    EventPaths,
    FitOptions,
    available_marks,
    calendar_features,
)

DIRECTIONS = 2
_UNKNOWN_MARK = "unknown"
_MAX_COUNT_BUCKET = 128
_MAX_HIDDEN = 32
_MAX_EPOCHS = 8
_MAX_MARKS = 8
_MAX_THREADS = 8
# Day-level batches are tiny: torch intra-op parallelism costs more than it saves.
_TINY_TENSOR_THREADS = 1
_CONTEXT_DAYS = 96
_WINDOW_STRIDE = 48
_BATCH_WINDOWS = 32
_LEARNING_RATE = 0.02
_DIRECTION_WEIGHT = 0.5
_MARK_WEIGHT = 0.5
_AMOUNT_WEIGHT = 0.5
_POSITIVE_AMOUNT_BINS = 8


def _softmax(values):
    values = np.asarray(values, dtype=np.float64)
    shifted = np.exp(values - values.max(axis=-1, keepdims=True))
    return shifted / shifted.sum(axis=-1, keepdims=True)


def _categorical(prob, uniform):
    """One inverse-CDF draw per row; the last class absorbs float rounding."""
    prob = np.asarray(prob, dtype=np.float64)
    cut = np.asarray(uniform, dtype=np.float64).reshape(-1, 1)
    index = (np.cumsum(prob, axis=-1) <= cut).sum(axis=-1)
    return np.minimum(index, prob.shape[-1] - 1).astype(np.int64)


def _pad(values, length):
    values = np.asarray(values)
    if len(values) == length:
        return values
    padded = np.zeros((length,) + values.shape[1:], dtype=values.dtype)
    padded[: len(values)] = values
    return padded


def _batch_loss(count_logits, direction_logits, mark_logits, amount_logits, count_target,
                direction_target, mark_target, amount_target, valid):
    """Multi-task loss on shifted steps: input day t only ever grades target day t+1."""
    graded = valid.sum().clamp_min(1.0)
    count_loss = (-(torch.log_softmax(count_logits[:, :-1], -1) * count_target).sum(-1) * valid).sum() / graded
    direction_weight = valid * (direction_target.sum(-1) > 0).float()
    direction_denom = direction_weight.sum().clamp_min(1.0)
    direction_loss = (-(torch.log_softmax(direction_logits[:, :-1], -1) * direction_target).sum(-1)
                      * direction_weight).sum() / direction_denom
    mark_loss = (-(torch.log_softmax(mark_logits[:, :-1], -1) * mark_target).sum(-1).sum(-1)
                 * valid).sum() / graded
    amount_loss = (-(torch.log_softmax(amount_logits[:, :-1], -1) * amount_target).sum(-1).sum(-1).sum(-1)
                   * valid).sum() / graded
    return (count_loss + _DIRECTION_WEIGHT * direction_loss + _MARK_WEIGHT * mark_loss
            + _AMOUNT_WEIGHT * amount_loss)


class _DayGRU(torch.nn.Module):
    def __init__(self, n_features, hidden_size, n_marks, n_buckets, n_amount_bins):
        super().__init__()
        self.n_marks = n_marks
        self.n_buckets = n_buckets
        self.n_amount_bins = n_amount_bins
        self.gru = torch.nn.GRU(n_features, hidden_size, batch_first=True)
        self.count_head = torch.nn.Linear(hidden_size, n_buckets)
        self.direction_head = torch.nn.Linear(hidden_size, DIRECTIONS)
        self.mark_head = torch.nn.Linear(hidden_size, DIRECTIONS * n_marks)
        self.amount_head = torch.nn.Linear(hidden_size, DIRECTIONS * n_marks * n_amount_bins)

    def sequence(self, features, state=None):
        return self.gru(features, state)

    def heads(self, hidden):
        """Decode next-day distributions from one hidden state row per scenario."""
        marks = self.mark_head(hidden).view(-1, DIRECTIONS, self.n_marks)
        amounts = self.amount_head(hidden).view(-1, DIRECTIONS, self.n_marks, self.n_amount_bins)
        return self.count_head(hidden), self.direction_head(hidden), marks, amounts

    def forward(self, features):
        output, _ = self.sequence(features)
        count, direction, marks, amounts = self.heads(output.reshape(-1, output.shape[-1]))
        steps = (output.shape[0], output.shape[1])
        return (count.view(steps[0], steps[1], self.n_buckets),
                direction.view(steps[0], steps[1], DIRECTIONS),
                marks.view(steps[0], steps[1], DIRECTIONS, self.n_marks),
                amounts.view(steps[0], steps[1], DIRECTIONS, self.n_marks, self.n_amount_bins))


class Model:
    """Day-resolution GRU event generator: bounded counts, marks, binned amounts."""

    def __init__(self, options: FitOptions | None = None):
        self.options = options or FitOptions()
        requested = getattr(self.options, "device", "cpu")
        if requested == "auto":
            requested = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(requested)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA was requested but is unavailable")
        self.count_cap = int(max(1, min(_MAX_COUNT_BUCKET, self.options.max_events_per_day)))
        self.hidden_size = int(max(4, min(_MAX_HIDDEN, self.options.hidden_size)))
        self.epochs = int(max(1, min(_MAX_EPOCHS, self.options.epochs)))
        # One window may not exceed the training-row budget, so the row cap is strict.
        self.context_days = int(min(_CONTEXT_DAYS, max(2, int(self.options.max_training_rows))))
        # options.threads is honoured as an upper bound; the measured optimum for these
        # batch shapes is one thread, so the effective count is clamped.
        self.threads_requested = int(max(1, min(self.options.threads, _MAX_THREADS)))
        self.threads_used = int(min(self.threads_requested, _TINY_TENSOR_THREADS))
        self.scale = np.ones(DIRECTIONS)
        self.n_amount_bins = _POSITIVE_AMOUNT_BINS + 1  # bin 0 is the exact zero-amount mass
        self.edges = [np.zeros(_POSITIVE_AMOUNT_BINS - 1) for _ in range(DIRECTIONS)]
        self.amount_pools = {}
        self.marks = [_UNKNOWN_MARK]
        self.mark_index = {_UNKNOWN_MARK: 0}
        self.amounts = ConditionalAmounts()
        self.net = None
        self.n_features = 0
        self.final_loss = float("nan")
        self._mean = None
        self._std = None
        self.diagnostics = {}

    @property
    def n_marks(self):
        return len(self.marks)

    @property
    def n_buckets(self):
        return self.count_cap + 1

    # ---------------------------------------------------------------- training

    def fit(self, histories: list[EventHistory]) -> "Model":
        usable = sorted((h for h in histories if len(h.dates) > 1), key=lambda h: h.company_id)
        if not usable:
            raise ValueError("event GRU needs a history with at least two days")
        observed_counts = [h.daily_counts[h.known].sum(axis=1) for h in usable if h.known.any()]
        maximum = max((int(values.max()) for values in observed_counts if len(values)), default=0)
        self.count_cap = max(1, min(maximum, self.options.max_events_per_day, _MAX_COUNT_BUCKET))
        self.marks = [_UNKNOWN_MARK] + self._fit_marks(usable)
        self.mark_index = {mark: slot for slot, mark in enumerate(self.marks)}
        self.scale = self._fit_scale(usable)
        self.edges, self.amount_pools = self._fit_amount_bins(usable)
        self.amounts = ConditionalAmounts().fit(usable)
        sequences = [self._history_sequence(h) for h in usable]
        observed = [seq["raw"][seq["known"]] for seq in sequences if seq["known"].any()]
        if not observed:
            raise ValueError("event GRU needs at least one observed fit day")
        observed = np.concatenate(observed, axis=0)
        self._mean = observed.mean(axis=0)
        self._std = np.maximum(observed.std(axis=0), 1e-3)
        self.n_features = observed.shape[1]
        windows, rows = self._windows(sequences)
        self._train(windows)
        self.diagnostics = {
            "model": "gru",
            "companies": len(usable),
            "marks": list(self.marks),
            "count_cap": self.count_cap,
            "hidden_size": self.hidden_size,
            "epochs": self.epochs,
            "context_days": self.context_days,
            "training_rows": rows,
            "training_windows": len(windows),
            "trained": bool(windows),
            "final_loss": self.final_loss,
            "amount_bins": self.n_amount_bins,
            "amount_bin_donors": len(self.amount_pools),
            "threads_requested": self.threads_requested,
            "threads_used": self.threads_used,
            "amount_fallback": "ConditionalAmounts pools when a positive bin has no donors",
            "device": str(self.device),
        }
        return self

    @staticmethod
    def _fit_marks(histories):
        tally = {}
        for h in histories:
            for mark, count in h.events.category.astype(str).value_counts().items():
                tally[mark] = tally.get(mark, 0) + int(count)
        names = [mark for mark in available_marks(histories) if mark != _UNKNOWN_MARK]
        names.sort(key=lambda mark: (-tally.get(mark, 0), mark))
        return names[:_MAX_MARKS]

    @staticmethod
    def _fit_scale(histories):
        """Fit-only amount scale; sampled amounts never move the feature scaling."""
        scale = np.ones(DIRECTIONS)
        for direction in range(DIRECTIONS):
            values = [h.events.loc[(h.events.direction == direction) & (h.events.amount > 0),
                                   "amount"].to_numpy(float) for h in histories]
            values = np.concatenate(values) if values else np.empty(0)
            if len(values):
                scale[direction] = float(np.median(values))
        return scale

    def _fit_amount_bins(self, histories):
        """Fit-only log1p bin edges and within-bin donors, in fit-scale units."""
        quantiles = np.linspace(0.0, 1.0, _POSITIVE_AMOUNT_BINS + 1)[1:-1]
        edges = []
        for direction in range(DIRECTIONS):
            values = [h.events.loc[(h.events.direction == direction) & (h.events.amount > 0),
                                   "amount"].to_numpy(float) / self.scale[direction]
                      for h in histories]
            values = np.concatenate(values) if values else np.empty(0)
            edges.append(np.quantile(np.log1p(values), quantiles) if len(values)
                         else np.zeros(_POSITIVE_AMOUNT_BINS - 1))
        self.edges = edges
        donors = {}
        for h in histories:
            events = h.events
            for direction in range(DIRECTIONS):
                rows = events[events.direction == direction]
                if not len(rows):
                    continue
                amounts = rows.amount.to_numpy(float)
                bins = self._event_bins(direction, amounts)
                normalized = amounts / self.scale[direction]
                for slot in range(1, self.n_amount_bins):       # bin 0 is exact zero
                    donors.setdefault((direction, slot), []).append(normalized[bins == slot])
        pools = {key: np.concatenate(parts) for key, parts in donors.items()}
        return edges, {key: pool for key, pool in pools.items() if len(pool)}

    def _event_bins(self, direction, amounts):
        amounts = np.asarray(amounts, dtype=np.float64)
        bins = np.digitize(np.log1p(amounts / self.scale[direction]), self.edges[direction]) + 1
        bins = np.minimum(bins, self.n_amount_bins - 1)
        bins[amounts <= 0] = 0
        return bins

    def _history_sequence(self, history):
        """Fit-only encoding of every history day, plus the day-level targets."""
        dates = np.asarray(history.dates, dtype="datetime64[D]")
        known = np.asarray(history.known, dtype=bool)
        counts = np.nan_to_num(history.daily_counts, nan=0.0)
        amounts = np.nan_to_num(history.daily_amounts, nan=0.0)
        marks = self._mark_counts(history.events, dates)
        bins = self._amount_bin_counts(history.events, dates)
        calendar = calendar_features(dates).to_numpy(np.float32)
        return {
            "dates": dates,
            "known": known,
            "counts": counts,
            "amounts": amounts,
            "marks": marks,
            "bins": bins,
            "raw": self._raw_features(known, counts, amounts, marks, calendar, self.scale),
        }

    def _mark_counts(self, events, dates):
        result = np.zeros((len(dates), DIRECTIONS, self.n_marks), dtype=np.float64)
        if len(events):
            day = (events.date.to_numpy(dtype="datetime64[D]") - dates[0]).astype(int)
            slot = np.array([self.mark_index.get(str(mark), 0) for mark in events.category], dtype=int)
            np.add.at(result, (day, events.direction.to_numpy(int), slot), 1.0)
        return result

    def _amount_bin_counts(self, events, dates):
        result = np.zeros((len(dates), DIRECTIONS, self.n_marks, self.n_amount_bins), dtype=np.float64)
        if len(events):
            day = (events.date.to_numpy(dtype="datetime64[D]") - dates[0]).astype(int)
            directions = events.direction.to_numpy(int)
            amounts = events.amount.to_numpy(float)
            marks = np.array([self.mark_index.get(str(mark), 0) for mark in events.category], dtype=int)
            slots = np.zeros(len(events), dtype=int)
            for direction in range(DIRECTIONS):
                chosen = directions == direction
                if chosen.any():
                    slots[chosen] = self._event_bins(direction, amounts[chosen])
            np.add.at(result, (day, directions, marks, slots), 1.0)
        return result

    def _raw_features(self, known, counts, amounts, marks, calendar, scale):
        """Permutation-invariant next-day input: own day only, never the target day."""
        counts = np.asarray(counts, dtype=np.float64)
        total = counts.sum(axis=1)
        shares = np.asarray(marks, dtype=np.float64) / np.maximum(counts, 1.0)[:, :, None]
        parts = [
            np.asarray(known, dtype=np.float64).reshape(-1, 1),
            (total > 0).astype(np.float64).reshape(-1, 1),
            np.log1p(counts),
            np.log1p(np.asarray(amounts, dtype=np.float64) / np.asarray(scale, dtype=np.float64)),
            shares.reshape(len(counts), -1),
            np.asarray(calendar, dtype=np.float64),
        ]
        return np.concatenate(parts, axis=1)

    def _standardize(self, features):
        return ((np.asarray(features, dtype=np.float64) - self._mean) / self._std).astype(np.float32)

    def _targets(self, counts, marks, bins, known):
        """Targets indexed by target day: row t is graded from the step that read day t-1."""
        counts = np.asarray(counts, dtype=np.float64)
        total = counts.sum(axis=1)
        bucket = np.minimum(total, self.count_cap).astype(np.int64)
        onehot = np.zeros((len(total), self.n_buckets), dtype=np.float32)
        onehot[np.arange(len(total)), bucket] = 1.0
        known = np.asarray(known, dtype=bool)
        valid = np.zeros(len(total), dtype=bool)
        valid[1:] = known[1:] & known[:-1]
        shared = np.maximum(total, 1.0)
        return {
            "bucket": bucket,
            "count": onehot,
            "direction": (counts / shared[:, None]).astype(np.float32),
            "mark": (np.asarray(marks, dtype=np.float64) / shared[:, None, None]).astype(np.float32),
            "amount": (np.asarray(bins, dtype=np.float64) / shared[:, None, None, None]).astype(np.float32),
            "valid": valid,
        }

    def _windows(self, sequences):
        budget = max(1, int(self.options.max_training_rows))
        length = self.context_days
        windows = []
        rows = 0
        for seq in sequences:
            targets = self._targets(seq["counts"], seq["marks"], seq["bins"], seq["known"])
            features = self._standardize(seq["raw"])
            days = len(features)
            start = max(0, days - length)  # most recent window first
            while start >= 0 and rows < budget:
                end = min(start + length, days)
                valid = targets["valid"][start:end]
                if valid.any():
                    extra = int(valid.sum())
                    if windows and rows + extra > budget:
                        break
                    windows.append({
                        "features": _pad(features[start:end], length),
                        "valid": _pad(valid, length).astype(np.float32),
                        "count": _pad(targets["count"][start:end], length),
                        "direction": _pad(targets["direction"][start:end], length),
                        "mark": _pad(targets["mark"][start:end], length),
                        "amount": _pad(targets["amount"][start:end], length),
                    })
                    rows += extra
                start -= _WINDOW_STRIDE
        return windows, rows

    def _train(self, windows):
        torch.manual_seed(int(self.options.seed))
        torch.set_num_threads(self.threads_used)
        self.net = _DayGRU(self.n_features, self.hidden_size, self.n_marks, self.n_buckets,
                           self.n_amount_bins).to(self.device)
        self.final_loss = float("nan")
        if not windows:
            self.net.eval()
            return
        optimizer = torch.optim.Adam(self.net.parameters(), lr=_LEARNING_RATE)
        sampler = np.random.default_rng(int(self.options.seed) + 1)
        self.net.train()
        for _ in range(self.epochs):
            order = sampler.permutation(len(windows))
            for begin in range(0, len(order), _BATCH_WINDOWS):
                batch = order[begin:begin + _BATCH_WINDOWS]
                features = torch.from_numpy(np.stack([windows[i]["features"] for i in batch])).to(self.device)
                count_logits, direction_logits, mark_logits, amount_logits = self.net(features)
                loss = _batch_loss(
                    count_logits, direction_logits, mark_logits, amount_logits,
                    torch.from_numpy(np.stack([windows[i]["count"] for i in batch])).to(self.device)[:, 1:],
                    torch.from_numpy(np.stack([windows[i]["direction"] for i in batch])).to(self.device)[:, 1:],
                    torch.from_numpy(np.stack([windows[i]["mark"] for i in batch])).to(self.device)[:, 1:],
                    torch.from_numpy(np.stack([windows[i]["amount"] for i in batch])).to(self.device)[:, 1:],
                    torch.from_numpy(np.stack([windows[i]["valid"] for i in batch])).to(self.device)[:, 1:],
                )
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                self.final_loss = float(loss.item())
        self.net.eval()

    # ---------------------------------------------------------------- sampling

    def sample(self, history: EventHistory, horizon: int, n_paths: int,
               rng: np.random.Generator) -> EventPaths:
        if self.net is None:
            raise RuntimeError("fit the event GRU before sampling")
        horizon, n_paths = int(horizon), int(n_paths)
        if horizon < 1 or n_paths < 1:
            raise ValueError("positive horizon and path count required")
        seq = self._history_sequence(history)
        context = self._standardize(seq["raw"][-self.context_days:])
        future = (np.asarray(history.as_of, dtype="datetime64[D]")
                  + np.arange(1, horizon + 1, dtype=np.int64).astype("timedelta64[D]"))
        allowed = history.allowed(future)
        calendar_rows = calendar_features(future).to_numpy(np.float32)
        pools = {}
        records = []
        suppressed = 0
        capped = 0
        fallback = 0
        self.net.eval()
        torch.set_num_threads(self.threads_used)
        with torch.no_grad():
            _, state = self.net.sequence(torch.from_numpy(context[None]).to(self.device))
            state = state.repeat(1, n_paths, 1)
            for step in range(horizon):
                count_logits, direction_logits, mark_logits, amount_logits = self.net.heads(state[-1])
                counts = _categorical(_softmax(count_logits.detach().cpu().numpy()), rng.random(n_paths))
                if not allowed[step]:
                    suppressed += int((counts > 0).sum())
                    counts = np.zeros_like(counts)
                capped += int((counts >= self.count_cap).sum())
                day_counts = np.zeros((n_paths, DIRECTIONS))
                day_amounts = np.zeros((n_paths, DIRECTIONS))
                day_marks = np.zeros((n_paths, DIRECTIONS, self.n_marks))
                total = int(counts.sum())
                if total:
                    owner = np.repeat(np.arange(n_paths), counts)
                    directions = _categorical(_softmax(direction_logits.detach().cpu().numpy())[owner], rng.random(total))
                    mark_prob = _softmax(mark_logits.detach().cpu().numpy())
                    slots = np.zeros(total, dtype=np.int64)
                    for direction in range(DIRECTIONS):
                        chosen = directions == direction
                        if chosen.any():
                            slots[chosen] = _categorical(mark_prob[owner[chosen], direction],
                                                         rng.random(int(chosen.sum())))
                    # learned (direction, mark) amount-bin distribution, exact zero in bin 0
                    bin_prob = _softmax(amount_logits.detach().cpu().numpy())
                    values = np.zeros(total)
                    for direction in range(DIRECTIONS):
                        chosen = np.flatnonzero(directions == direction)
                        if not len(chosen):
                            continue
                        bins = _categorical(bin_prob[owner[chosen], direction, slots[chosen]],
                                            rng.random(len(chosen)))
                        values[chosen], missing = self._bin_values(direction, bins,
                                                                   self.scale[direction], rng)
                        if not missing.any():
                            continue
                        fallback += int(missing.sum())
                        for mark_slot in np.unique(slots[chosen][missing]):
                            group = chosen[missing][slots[chosen][missing] == mark_slot]
                            donor = self._amount_pool(history, direction, self.marks[mark_slot], pools)
                            values[group] = rng.choice(donor, len(group))
                    np.add.at(day_counts, (owner, directions), 1.0)
                    np.add.at(day_amounts, (owner, directions), values)
                    np.add.at(day_marks, (owner, directions, slots), 1.0)
                    for path, direction, slot, value in zip(owner.tolist(), directions.tolist(),
                                                            slots.tolist(), values.tolist()):
                        records.append({"path": path, "day": step + 1, "direction": direction,
                                        "amount": float(value), "category": self.marks[slot]})
                known = np.ones(n_paths, dtype=bool)
                calendar = np.broadcast_to(calendar_rows[step], (n_paths, calendar_rows.shape[1]))
                raw = self._raw_features(known, day_counts, day_amounts, day_marks, calendar, self.scale)
                _, state = self.net.sequence(torch.from_numpy(self._standardize(raw)[:, None, :]).to(self.device), state)
        return EventPaths.from_records(history, horizon, n_paths, records, diagnostics={
            "model": "gru",
            "n_events": len(records),
            "count_cap": self.count_cap,
            "count_cap_hits": capped,
            "masked_day_paths": suppressed,
            "context_days": int(min(len(seq["dates"]), self.context_days)),
            "observed_context_days": int(seq["known"][-self.context_days:].sum()),
            "marks": list(self.marks),
            "amount_bins": self.n_amount_bins,
            "device": str(self.device),
            "amount_fallback_events": fallback,
            "zero_amount_events": sum(1 for record in records if record["amount"] == 0.0),
            "threads_requested": self.threads_requested,
            "threads_used": self.threads_used,
            "training_rows": self.diagnostics.get("training_rows", 0),
            "epochs": self.epochs,
            "hidden_size": self.hidden_size,
        })

    def _bin_values(self, direction, bins, scale, rng):
        """Decode donors in their fitted units; bin 0 is exact zero mass."""
        values = np.zeros(len(bins))
        missing = np.zeros(len(bins), dtype=bool)
        for slot in range(1, self.n_amount_bins):
            chosen = bins == slot
            if not chosen.any():
                continue
            pool = self.amount_pools.get((direction, slot))
            if pool is None or not len(pool):
                missing |= chosen
                continue
            values[chosen] = rng.choice(pool, int(chosen.sum())) * scale
        return values, missing

    def _amount_pool(self, history, direction, mark, cache):
        key = (direction, mark)
        pool = cache.get(key)
        if pool is None:
            pool = self._resolve_amount_pool(history, direction, mark)
            cache[key] = pool
        return pool

    def _resolve_amount_pool(self, history, direction, mark):
        """Mirror of ConditionalAmounts key lookup, resolved once per sample call."""
        local = history.events
        local = local[(local.direction == direction) & (local.category.astype(str) == mark)
                      & (local.date >= pd.Timestamp(history.as_of - np.timedelta64(181, "D")))]
        if len(local) >= 3:
            return local.amount.to_numpy(float)
        for key in ((history.industry, direction, mark), ("*", direction, mark), ("*", direction, "*")):
            values = self.amounts.pools.get(key)
            if values is not None and len(values):
                return np.asarray(values, dtype=float) * history.amount_scale(direction)
        return np.zeros(1)

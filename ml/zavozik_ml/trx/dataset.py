"""Окна последовательностей для обучения трансформера.

Пример = окно из seq_len + 1 подряд идущих операций одной компании/клиента:
вход — первые seq_len, цель — следующая операция на каждой позиции.

Источники (шарды) задаются с фильтром: какие роли последовательностей брать
и до какого дня (отсечка: данные после неё модель не видит). Словари типов
разных шардов сводятся к общему словарю модели.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
from torch.utils.data import IterableDataset

from .schema import DIR_UNKNOWN, TypeVocab
from .shards import Shard

INPUT_FIELDS = ("delta", "dir", "type", "amount_bin", "log_amount", "weekday", "dom", "month", "off_before", "flags")
TARGET_FIELDS = ("delta", "dir", "type", "amount_bin", "weekday", "dom", "month", "off_before", "flags")
SOURCE_IDS = {"mbd": 0, "case": 1}
IGNORE = -100


@dataclass
class Source:
    shard: Shard
    roles: set[str] | None = None  # None — все последовательности
    max_day: int | None = None  # включительно; None — без отсечки
    weight: float = 1.0
    remap: np.ndarray = field(default=None, repr=False)  # тип шарда → тип модели


def build_vocab(sources: list[Source], base: TypeVocab | None = None) -> TypeVocab:
    """Общий словарь модели: base (например, предобученной) + новые типы шардов."""
    vocab = TypeVocab(list(base.names)) if base else TypeVocab()
    for s in sources:
        vocab = vocab.merged(s.shard.vocab)
    for s in sources:
        s.remap = np.array([vocab.get(n) for n in s.shard.vocab.names], dtype=np.int64)
    return vocab


def _eligible(src: Source, min_len: int) -> tuple[np.ndarray, np.ndarray]:
    """Индексы подходящих последовательностей и их длина с учётом отсечки."""
    idx, lens = [], []
    days = src.shard.arrays["day"]
    for i, seq in enumerate(src.shard.sequences):
        if src.roles is not None and seq.get("role") not in src.roles:
            continue
        lo, hi = src.shard.offsets[i], src.shard.offsets[i + 1]
        n = hi - lo
        if src.max_day is not None:
            n = int(np.searchsorted(np.asarray(days[lo:hi]), src.max_day, side="right"))
        if n >= min_len:
            idx.append(i)
            lens.append(n)
    return np.array(idx, dtype=np.int64), np.array(lens, dtype=np.int64)


def make_example(src: Source, seq: int, start: int, length: int) -> dict[str, np.ndarray]:
    """Окно [start, start + length + 1) → входы и цели длины length."""
    t = src.shard.slice(seq, start, start + length + 1)
    t["type"] = src.remap[t["type"]]
    t["src"] = np.full(len(t["day"]), SOURCE_IDS.get(src.shard.meta.source, 1), dtype=np.int64)
    ex = {f"x_{k}": t[k][:-1] for k in INPUT_FIELDS}
    ex["x_src"] = t["src"][:-1]
    ex["x_day"] = t["day"][:-1]
    for k in TARGET_FIELDS:
        ex[f"y_{k}"] = t[k][1:]
    y_dir = ex["y_dir"].astype(np.int64)
    ex["y_dir"] = np.where(y_dir == DIR_UNKNOWN, IGNORE, y_dir)  # направление MBD может быть неизвестно
    return ex


def collate(batch: list[dict[str, np.ndarray]]) -> dict[str, torch.Tensor]:
    """Дополнение до максимальной длины в батче; mask = 1 у настоящих позиций."""
    n = max(len(b["x_delta"]) for b in batch)
    out: dict[str, torch.Tensor] = {}
    for k in batch[0]:
        a0 = batch[0][k]
        dtype = np.float32 if a0.dtype.kind == "f" else np.int64
        pad = IGNORE if k.startswith("y_") and k not in ("y_weekday", "y_dom", "y_month", "y_off_before", "y_flags") else 0
        shape = (len(batch), n) + a0.shape[1:]
        arr = np.full(shape, pad, dtype=dtype)
        for i, b in enumerate(batch):
            arr[i, : len(b[k])] = b[k]
        out[k] = torch.from_numpy(arr)
    mask = np.zeros((len(batch), n), dtype=np.bool_)
    for i, b in enumerate(batch):
        mask[i, : len(b["x_delta"])] = True
    out["mask"] = torch.from_numpy(mask)
    return out


class WindowDataset(IterableDataset):
    """Бесконечный поток случайных окон; вероятность последовательности —
    пропорционально её длине (каждая операция примерно равновероятна) с весом источника."""

    def __init__(self, sources: list[Source], seq_len: int, min_len: int = 16, seed: int = 0):
        self.sources = sources
        self.seq_len = seq_len
        self.min_len = min_len
        self.seed = seed
        self._index = [_eligible(s, min_len) for s in sources]
        weights = []
        for s, (idx, lens) in zip(sources, self._index):
            w = np.minimum(lens, seq_len * 4).astype(float)
            weights.append(w / max(w.sum(), 1.0) * s.weight)
        self._flat = [(si, i) for si, (idx, _) in enumerate(self._index) for i in range(len(idx))]
        p = np.concatenate(weights) if weights else np.array([])
        if not len(self._flat):
            raise ValueError("нет последовательностей, подходящих под фильтры и min_len")
        self._p = p / p.sum()

    def n_tokens(self) -> int:
        return int(sum(lens.sum() for _, lens in self._index))

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        # В основном процессе — только seed (воспроизводимая валидация); в
        # процессах DataLoader — свой поток на каждый процесс и эпоху.
        worker = (info.id * 9973 + info.seed % 2**31) if info else 0
        rng = np.random.default_rng(self.seed + worker)
        while True:
            k = rng.choice(len(self._flat), p=self._p)
            si, j = self._flat[k]
            seq, n = self._index[si][0][j], self._index[si][1][j]
            length = min(self.seq_len, n - 1)
            start = int(rng.integers(0, n - length))  # окно целиком до отсечки
            yield make_example(self.sources[si], int(seq), start, length)


def validation_windows(sources: list[Source], seq_len: int, n: int, min_len: int = 16, seed: int = 1) -> list[dict]:
    """Фиксированный набор окон для валидации (одинаковый между запусками)."""
    ds = WindowDataset(sources, seq_len, min_len, seed)
    it = iter(ds)
    return [next(it) for _ in range(n)]

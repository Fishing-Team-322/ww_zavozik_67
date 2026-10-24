"""Формат подготовленных данных на диске и чтение через memmap.

Каталог шарда:
  meta.json         — ShardMeta + описание полей (dtype, ширина);
  vocab.json        — словарь типов операций;
  sequences.json    — id последовательностей (компании/клиенты) и их атрибуты;
  offsets.bin       — int64[n_seq + 1]: границы последовательностей в токенах;
  <поле>.bin        — по файлу на поле, токены всех последовательностей подряд.

Поля пишутся потоком (append), поэтому MBD на сотни миллионов операций
готовится без загрузки в память, а читается memmap'ом кусками.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .schema import (
    ShardMeta,
    TypeVocab,
    amount_bin,
    calendar_fields,
    delta_days,
    log_amount,
)

# Поле → (dtype, ширина). Ширина > 1 — матрица [n_tokens, width].
FIELDS: dict[str, tuple[str, int]] = {
    "day": ("int32", 1),  # день от 1970-01-01
    "delta": ("int8", 1),
    "dir": ("int8", 1),
    "type": ("int32", 1),
    "amount_bin": ("int16", 1),
    "log_amount": ("float32", 1),
    "amount": ("float64", 1),  # для оценки прогноза в рублях
    "weekday": ("int8", 1),
    "dom": ("int8", 1),
    "month": ("int8", 1),
    "off_before": ("int8", 1),
    "flags": ("int8", 4),
}


def encode_sequence(days: np.ndarray, direction: np.ndarray, types: np.ndarray, amount: np.ndarray) -> dict[str, np.ndarray]:
    """Поля токенов одной последовательности, отсортированной по дню."""
    days = np.asarray(days, dtype=np.int64)
    out = {
        "day": days,
        "delta": delta_days(days),
        "dir": np.asarray(direction, dtype=np.int64),
        "type": np.asarray(types, dtype=np.int64),
        "amount_bin": amount_bin(amount),
        "log_amount": log_amount(amount),
        "amount": np.abs(np.asarray(amount, dtype=np.float64)),
    }
    out.update(calendar_fields(days))
    return out


class ShardWriter:
    """Потоковая запись последовательностей в каталог шарда."""

    def __init__(self, directory: Path, source: str, vocab: TypeVocab):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.vocab = vocab
        self.files = {name: open(self.dir / f"{name}.bin", "wb") for name in FIELDS}
        self.offsets = [0]
        self.sequences: list[dict] = []

    def add(self, seq_id: str, fields: dict[str, np.ndarray], **attrs) -> None:
        n = len(fields["day"])
        if n == 0:
            return
        for name, (dtype, width) in FIELDS.items():
            a = np.asarray(fields[name]).astype(dtype, copy=False)
            if a.shape != ((n,) if width == 1 else (n, width)):
                raise ValueError(f"{seq_id}: поле {name} формы {a.shape}")
            self.files[name].write(np.ascontiguousarray(a).tobytes())
        self.offsets.append(self.offsets[-1] + n)
        self.sequences.append({"id": seq_id, **attrs})

    def close(self, **notes) -> ShardMeta:
        for f in self.files.values():
            f.close()
        np.asarray(self.offsets, dtype=np.int64).tofile(self.dir / "offsets.bin")
        (self.dir / "sequences.json").write_text(json.dumps(self.sequences, ensure_ascii=False))
        self.vocab.save(self.dir / "vocab.json")
        meta = ShardMeta(source=self.source, n_tokens=self.offsets[-1], n_sequences=len(self.sequences),
                         notes={"fields": {k: list(v) for k, v in FIELDS.items()}, **notes})
        meta.save(self.dir / "meta.json")
        return meta


@dataclass
class Shard:
    """Чтение шарда. Файлы открываются лениво — объект можно передавать в
    процессы DataLoader (в Windows они запускаются через spawn)."""

    directory: Path

    def __post_init__(self) -> None:
        self.directory = Path(self.directory)
        self.meta = ShardMeta.load(self.directory / "meta.json")
        self.vocab = TypeVocab.load(self.directory / "vocab.json")
        self.sequences = json.loads((self.directory / "sequences.json").read_text())
        self.offsets = np.fromfile(self.directory / "offsets.bin", dtype=np.int64)
        self._arrays: dict[str, np.ndarray] | None = None

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_arrays"] = None  # memmap не сериализуем, откроется в процессе заново
        return state

    @property
    def arrays(self) -> dict[str, np.ndarray]:
        if self._arrays is None:
            n = self.meta.n_tokens
            self._arrays = {}
            for name, (dtype, width) in FIELDS.items():
                shape = (n,) if width == 1 else (n, width)
                self._arrays[name] = np.memmap(self.directory / f"{name}.bin", dtype=dtype, mode="r", shape=shape)
        return self._arrays

    def __len__(self) -> int:
        return len(self.sequences)

    def lengths(self) -> np.ndarray:
        return np.diff(self.offsets)

    def slice(self, seq: int, start: int = 0, stop: int | None = None) -> dict[str, np.ndarray]:
        """Токены последовательности seq в диапазоне [start, stop)."""
        lo = self.offsets[seq]
        hi = self.offsets[seq + 1]
        a, b = lo + start, hi if stop is None else min(hi, lo + stop)
        return {name: np.asarray(arr[a:b]) for name, arr in self.arrays.items()}

"""Линейный классификатор категорий (мультиномиальная логистическая регрессия).

Инференс — только numpy: признаки хэшированные (text.features), веса —
матрица N_FEATURES × K, в артефакте хранятся только ненулевые строки.
Выход — всегда одна из CATEGORIES; при уверенности ниже min_confidence
отвечаем `other` (смысл операции не определить).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .text import CATEGORIES, N_FEATURES, OTHER, Op, cache_key, features

ARTIFACT_VERSION = 1


@dataclass
class Prediction:
    category: str
    confidence: float  # 0..1
    proba: np.ndarray | None = field(default=None, repr=False)


class Classifier:
    def __init__(self, W: np.ndarray, b: np.ndarray, temperature: float = 1.0, min_confidence: float = 0.3,
                 meta: dict | None = None):
        if W.shape != (N_FEATURES, len(CATEGORIES)) or b.shape != (len(CATEGORIES),):
            raise ValueError(f"bad weights shape {W.shape}, {b.shape}")
        if not np.isfinite(W).all() or not np.isfinite(b).all():
            raise ValueError("classifier weights must be finite")
        if not math.isfinite(temperature) or temperature <= 0 or not 0 <= min_confidence <= 1:
            raise ValueError("invalid classifier calibration")
        self.W = W.astype(np.float32, copy=False)
        self.b = b.astype(np.float32, copy=False)
        self.temperature = float(temperature)
        self.min_confidence = float(min_confidence)
        self.meta = meta or {}
        self._other = CATEGORIES.index(OTHER)

    # ------------------------------------------------------------ инференс
    def logits(self, ops: list[Op]) -> np.ndarray:
        out = np.empty((len(ops), len(CATEGORIES)), dtype=np.float32)
        cache: dict[tuple, int] = {}
        for i, op in enumerate(ops):
            k = cache_key(op)
            j = cache.get(k)
            if j is not None:
                out[i] = out[j]
                continue
            idx, val = features(op)
            out[i] = self.b + np.asarray(val, dtype=np.float32) @ self.W[np.asarray(idx, dtype=np.int64)]
            cache[k] = i
        return out

    def predict_proba(self, ops: list[Op]) -> np.ndarray:
        z = self.logits(ops) / self.temperature
        z -= z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)

    def predict(self, ops: list[Op]) -> list[Prediction]:
        if not ops:
            return []
        p = self.predict_proba(ops)
        top = p.argmax(axis=1)
        res = []
        for i, j in enumerate(top):
            conf = float(p[i, j])
            if not math.isfinite(conf):
                res.append(Prediction(OTHER, 0.0, p[i]))
            elif conf < self.min_confidence:
                res.append(Prediction(OTHER, conf, p[i]))
            else:
                res.append(Prediction(CATEGORIES[j], conf, p[i]))
        return res

    # ------------------------------------------------------------ артефакт
    def save(self, directory: Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        rows = np.flatnonzero(np.abs(self.W).max(axis=1) > 1e-4).astype(np.int32)
        np.savez_compressed(directory / "weights.npz", rows=rows, W=self.W[rows].astype(np.float16), b=self.b)
        meta = dict(self.meta, version=ARTIFACT_VERSION, categories=list(CATEGORIES), n_features=N_FEATURES,
                    temperature=self.temperature, min_confidence=self.min_confidence)
        (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "Classifier":
        directory = Path(directory)
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        if meta.get("version") != ARTIFACT_VERSION or meta.get("categories") != list(CATEGORIES) \
                or meta.get("n_features") != N_FEATURES:
            raise ValueError(f"{directory}: несовместимый артефакт классификатора")
        with np.load(directory / "weights.npz") as z:
            W = np.zeros((N_FEATURES, len(CATEGORIES)), dtype=np.float32)
            W[z["rows"]] = z["W"].astype(np.float32)
            b = z["b"]
        return cls(W, b, meta.get("temperature", 1.0), meta.get("min_confidence", 0.3), meta)


DEFAULT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "classifier"

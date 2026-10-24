"""Поля токена-операции и их кодирование. Без torch: используется и при
подготовке данных, и в модели.

Каждая операция кодируется набором целых полей (для эмбеддингов и голов
предсказания) и одним вещественным (точный логарифм суммы).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from zavozik_ml import calendar as cal

SCHEMA_VERSION = 1

# --- дни между операциями ---------------------------------------------------
# 0..MAX_DELTA — точное число дней после предыдущей операции компании;
# DELTA_FAR — больше MAX_DELTA (пауза, пропуск выписки): при генерации это
# «до конца горизонта ничего не будет».
MAX_DELTA = 30
DELTA_FAR = MAX_DELTA + 1
N_DELTA = MAX_DELTA + 2

# --- суммы ------------------------------------------------------------------
# Логарифмические интервалы от 1 ₽ до 10^9 ₽: N_AMOUNT интервалов, ~18% ширина.
AMOUNT_LOG_MIN = 0.0
AMOUNT_LOG_MAX = 9.0
N_AMOUNT = 128

# --- направление ------------------------------------------------------------
DIR_IN, DIR_OUT, DIR_UNKNOWN = 0, 1, 2
N_DIR = 3

# --- типы операций ----------------------------------------------------------
# Общий словарь: 0 — заполнитель, 1 — неизвестный тип. Дальше — типы
# источников с префиксом («case:salary», «mbd:12_3»). Новые типы добавляются в
# конец, старые индексы не меняются — так дообучение расширяет словарь.
TYPE_PAD, TYPE_UNKNOWN = 0, 1

# Внутренние движения владельца: в бизнес-поток прогноза не входят.
INTERNAL_TYPES = frozenset({"case:own_transfer", "case:owner_loan"})

# --- календарь дня операции -------------------------------------------------
MAX_OFF_BEFORE = 12
# Корзины хеша id последовательности: разбиение компаний на обучение/валидацию.
N_BUCKETS = 100
CAL_FLAGS = ("is_workday", "is_tax_day", "is_pay10", "is_pay25")


@dataclass
class TypeVocab:
    """Словарь типов операций. Индекс = позиция в списке."""

    names: list[str] = field(default_factory=lambda: ["<pad>", "<unknown>"])

    def __post_init__(self) -> None:
        self._index = {n: i for i, n in enumerate(self.names)}

    def __len__(self) -> int:
        return len(self.names)

    def add(self, name: str) -> int:
        if name not in self._index:
            self._index[name] = len(self.names)
            self.names.append(name)
        return self._index[name]

    def get(self, name: str) -> int:
        return self._index.get(name, TYPE_UNKNOWN)

    def ids_with_prefix(self, prefix: str) -> list[int]:
        return [i for i, n in enumerate(self.names) if n.startswith(prefix)]

    def merged(self, other: "TypeVocab") -> "TypeVocab":
        """Этот словарь + новые типы из other в конце (индексы этого не меняются)."""
        out = TypeVocab(list(self.names))
        for n in other.names:
            out.add(n)
        return out

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "types": self.names}, ensure_ascii=False, indent=1))

    @classmethod
    def load(cls, path: Path) -> "TypeVocab":
        d = json.loads(Path(path).read_text())
        return cls(list(d["types"]))


def amount_bin(amount: np.ndarray) -> np.ndarray:
    """Номер логарифмического интервала суммы (по модулю)."""
    lg = np.log10(np.maximum(np.abs(amount), 1.0))
    b = (lg - AMOUNT_LOG_MIN) / (AMOUNT_LOG_MAX - AMOUNT_LOG_MIN) * N_AMOUNT
    return np.clip(b.astype(np.int64), 0, N_AMOUNT - 1)


def amount_from_bin(bins: np.ndarray, rng: np.random.Generator | None = None) -> np.ndarray:
    """Сумма из интервала: середина или случайная точка внутри (в логарифме)."""
    u = 0.5 if rng is None else rng.random(np.shape(bins))
    lg = AMOUNT_LOG_MIN + (np.asarray(bins) + u) * (AMOUNT_LOG_MAX - AMOUNT_LOG_MIN) / N_AMOUNT
    return np.power(10.0, lg)


def log_amount(amount: np.ndarray) -> np.ndarray:
    """Нормированный точный логарифм суммы, ~[0, 1]."""
    return (np.log10(np.maximum(np.abs(amount), 1.0)) / AMOUNT_LOG_MAX).astype(np.float32)


def delta_days(days: np.ndarray) -> np.ndarray:
    """Дни после предыдущей операции той же последовательности; первая — 0."""
    d = np.diff(days, prepend=days[:1])
    return np.where(d > MAX_DELTA, DELTA_FAR, np.maximum(d, 0)).astype(np.int64)


def calendar_fields(days: np.ndarray) -> dict[str, np.ndarray]:
    """Календарь дня операции. days — номер дня от 1970-01-01."""
    dates = days.astype("datetime64[D]")
    f = cal.features(dates, dates)
    weekday = ((days + 3) % 7).astype(np.int64)  # 1970-01-01 — четверг
    as_obj = dates.astype("datetime64[M]")
    month = (as_obj.astype(np.int64) % 12).astype(np.int64)  # 0 = январь
    dom = (dates - as_obj.astype("datetime64[D]")).astype(np.int64)  # 0..30
    return {
        "weekday": weekday,
        "dom": dom,
        "month": month,
        "off_before": np.minimum(f["off_before"], MAX_OFF_BEFORE).astype(np.int64),
        "flags": np.stack([f[k] for k in CAL_FLAGS], axis=1).astype(np.int8),
    }


@dataclass
class ShardMeta:
    """Описание подготовленного набора данных."""

    source: str  # "case" | "mbd" | ...
    n_tokens: int
    n_sequences: int
    schema_version: int = SCHEMA_VERSION
    notes: dict = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1))

    @classmethod
    def load(cls, path: Path) -> "ShardMeta":
        return cls(**json.loads(Path(path).read_text()))

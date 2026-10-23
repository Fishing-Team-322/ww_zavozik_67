"""Глобальный градиентный бустинг (LightGBM) по всем компаниям сразу.

Точечный прогноз: для пары (точка старта t0, горизонт h) модель предсказывает
приток и отток в день t0+h по признакам, известным на t0:
  * календарь целевого дня: день недели, число, месяц, дней до конца месяца;
  * уровень компании: средние потоки за 28/91 день, по тому же дню недели
    за 8 недель, доля активных дней;
  * «то же число месяц/два/три назад» (окно ±2 дня) — ловит зарплату,
    ЕНП 28-го, аренду и кредиты, даже если они сдвинулись с выходных;
  * регулярные списания по категориям (зарплата, налоги, аренда, ...);
  * отрасль.
Всё нормируется на масштаб компании, поэтому одна модель работает и для
кофейни, и для оптовика.

Распределение: пути = точечный прогноз + блоки остатков модели на прошлых
точках старта той же компании (весь 30-дневный блок целиком, чтобы
сохранить автокорреляцию ошибок — от неё зависит ширина коридора
накопленного остатка).
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .base import Forecaster, History, NotTrainedError, Paths, register
from .naive import MIN_CONFIDENT_DAYS, SeasonalNaive

MIN_HISTORY = 56
MAX_HORIZON = 30
TRAIN_STEP = 3  # шаг точек старта в обучении, дней
BLOCK_STEP = 7  # шаг псевдо-точек старта для блоков остатков, дней
MAX_BLOCKS = 40
MIN_BLOCKS = 4
CAL_DAYS = 60
TARGET_COVERAGE = 0.8
SPREAD_GRID = np.round(np.arange(1.0, 4.01, 0.25), 2)

PARAMS = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.3,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "num_threads": 0,
}
NUM_ROUNDS = 400


class _Series:
    """Префиксные суммы по ряду компании для быстрых оконных признаков."""

    def __init__(self, h: History):
        self.h = h
        self.n = len(h)
        valid = (~h.missing).astype(float)
        self.valid = valid
        self.inflow = h.inflow * valid
        self.outflow = h.outflow * valid
        self.regular = h.regular_outflow() * valid
        self.active = ((h.inflow + h.outflow) > 0).astype(float) * valid
        self.p = {k: np.concatenate([[0.0], np.cumsum(v)]) for k, v in
                  {"in": self.inflow, "out": self.outflow, "reg": self.regular, "valid": valid}.items()}
        self.d0 = np.datetime64(h.dates[0], "D")

    def wmean(self, key: str, t0: np.ndarray, w: int) -> np.ndarray:
        lo = np.maximum(t0 + 1 - w, 0)
        cnt = self.p["valid"][t0 + 1] - self.p["valid"][lo]
        return (self.p[key][t0 + 1] - self.p[key][lo]) / np.maximum(cnt, 1)

    def wsum_abs(self, key: str, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        """Сумма за [lo, hi] включительно; nan, если окно выходит за историю."""
        ok = (lo >= 0) & (hi < self.n)
        lo_c, hi_c = np.clip(lo, 0, self.n - 1), np.clip(hi, 0, self.n - 1)
        s = self.p[key][hi_c + 1] - self.p[key][lo_c]
        return np.where(ok, s, np.nan)


def _features(s: _Series, t0: np.ndarray, h: np.ndarray, industry_code: int) -> pd.DataFrame:
    t = t0 + h
    target = pd.DatetimeIndex(s.d0 + t.astype("timedelta64[D]"))
    scale = s.wmean("in", t0, 91) + s.wmean("out", t0, 91) + 1.0
    f = {
        "h": h,
        "weekday": target.day_of_week.to_numpy(),
        "dom": target.day.to_numpy(),
        "month": target.month.to_numpy(),
        "days_to_eom": (target.days_in_month - target.day).to_numpy(),
        "log_scale": np.log10(scale),
        "history_days": np.minimum(t0 + 1, 730),
        "frac_valid_91": (s.p["valid"][t0 + 1] - s.p["valid"][np.maximum(t0 - 90, 0)]) / np.minimum(t0 + 1, 91),
        "industry": np.full(len(t0), industry_code),
    }
    for key in ("in", "out", "reg"):
        for w in (28, 91):
            f[f"{key}_mean_{w}"] = s.wmean(key, t0, w) / scale
    f["in_trend"] = s.wmean("in", t0, 28) / (s.wmean("in", t0, 91) + 1.0)
    f["out_trend"] = s.wmean("out", t0, 28) / (s.wmean("out", t0, 91) + 1.0)

    # Тот же день недели за последние 8 недель (только известные дни <= t0).
    j0 = t - 7 * np.ceil(h / 7).astype(int)
    idx = j0[:, None] - 7 * np.arange(8)[None, :]
    ok = idx >= 0
    idx_c = np.clip(idx, 0, s.n - 1)
    v = s.valid[idx_c] * ok
    cnt = np.maximum(v.sum(axis=1), 1)
    f["in_wd_8w"] = (s.inflow[idx_c] * ok).sum(axis=1) / cnt / scale
    f["out_wd_8w"] = (s.outflow[idx_c] * ok).sum(axis=1) / cnt / scale
    f["active_wd_8w"] = (s.active[idx_c] * ok).sum(axis=1) / cnt

    # То же число месяц/два/три назад, окно ±2 дня.
    for m in (1, 2, 3):
        back = (target - pd.DateOffset(months=m)).to_numpy().astype("datetime64[D]")
        bi = (back - s.d0).astype(int)
        hi = np.minimum(bi + 2, t0)
        for key in ("in", "out", "reg"):
            f[f"{key}_dom_m{m}"] = s.wsum_abs(key, bi - 2, hi) / scale
    return pd.DataFrame(f), scale


@register
class GBMGlobal(Forecaster):
    name = "gbm_global"
    description = "LightGBM по всем компаниям: календарь, «то же число месяц назад», регулярные платежи"
    is_global = True

    def __init__(self) -> None:
        self.models: dict[str, lgb.Booster] = {}
        self.industries: list[str] = []
        self.spread = 1.0
        self.calibration: dict[str, float] = {}

    @property
    def ready(self) -> bool:
        return bool(self.models)

    # --- обучение ---

    def _industry_code(self, industry: str) -> int:
        try:
            return self.industries.index(industry)
        except ValueError:
            return -1

    def fit(self, histories: list[History]) -> None:
        self.industries = sorted({h.industry for h in histories})
        # Калибровка разброса: учимся без последних CAL_DAYS дней и подбираем
        # множитель так, чтобы коридор p10–p90 накопленного потока покрывал
        # 80% факта на этих днях. Потом переобучаемся на всём.
        head = [h.head(len(h) - CAL_DAYS) for h in histories if len(h) - CAL_DAYS > MIN_HISTORY + MAX_HORIZON]
        self.spread = 1.0
        self.models = self._train(head)
        self.spread, self.calibration = self._calibrate(histories)
        self.models = self._train(histories)

    def _train(self, histories: list[History]) -> dict[str, lgb.Booster]:
        frames, y_in, y_out = [], [], []
        for hist in histories:
            s = _Series(hist)
            t0s = _train_origins(hist)
            if not len(t0s):
                continue
            t0 = np.repeat(t0s, MAX_HORIZON)
            h = np.tile(np.arange(1, MAX_HORIZON + 1), len(t0s))
            X, scale = _features(s, t0, h, self._industry_code(hist.industry))
            frames.append(X)
            y_in.append(s.inflow[t0 + h] / scale)
            y_out.append(s.outflow[t0 + h] / scale)
        X = pd.concat(frames, ignore_index=True)
        models = {}
        for key, y in (("in", np.concatenate(y_in)), ("out", np.concatenate(y_out))):
            ds = lgb.Dataset(X, y, categorical_feature=["industry"], free_raw_data=True)
            models[key] = lgb.train(PARAMS, ds, NUM_ROUNDS)
        return models

    def _calibrate(self, histories: list[History]) -> tuple[float, dict[str, float]]:
        rng = np.random.default_rng(0)
        covered = np.zeros(len(SPREAD_GRID))
        total = 0
        for hist in histories:
            n = len(hist)
            for t0 in (n - 1 - MAX_HORIZON - 7 * k for k in range(4)):
                if t0 < MIN_HISTORY - 1 or hist.missing[t0 - MIN_HISTORY + 1 : t0 + MAX_HORIZON + 1].any():
                    continue
                c = self._components(hist.head(t0 + 1), MAX_HORIZON)
                if c is None:
                    continue
                mu_in, mu_out, r_in, r_out, scale = c
                k = rng.integers(len(r_in), size=200)
                actual = np.cumsum(hist.inflow - hist.outflow)[t0 + 1 : t0 + MAX_HORIZON + 1] - np.cumsum(
                    hist.inflow - hist.outflow
                )[t0]
                for i, a in enumerate(SPREAD_GRID):
                    net = np.cumsum(mu_in - mu_out + a * (r_in[k] - r_out[k]) * scale, axis=1)
                    lo, hi = np.quantile(net, [0.1, 0.9], axis=0)
                    covered[i] += ((actual >= lo) & (actual <= hi)).sum()
                total += MAX_HORIZON
        if total == 0:
            return 1.0, {}
        coverage = covered / total
        best = int(np.argmin(np.abs(coverage - TARGET_COVERAGE)))
        return float(SPREAD_GRID[best]), {f"{a:.2f}": round(float(c), 3) for a, c in zip(SPREAD_GRID, coverage)}

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for key, m in self.models.items():
            m.save_model(str(directory / f"{key}.txt"))
        meta = {"industries": self.industries, "spread": self.spread, "calibration": self.calibration}
        (directory / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))

    def load(self, directory: Path) -> bool:
        if not (directory / "meta.json").exists():
            return False
        meta = json.loads((directory / "meta.json").read_text())
        self.industries, self.spread = meta["industries"], meta.get("spread", 1.0)
        self.calibration = meta.get("calibration", {})
        self.models = {k: lgb.Booster(model_file=str(directory / f"{k}.txt")) for k in ("in", "out")}
        return True

    # --- прогноз ---

    def _predict(self, s: _Series, t0: np.ndarray, h: np.ndarray, industry: str) -> tuple[np.ndarray, np.ndarray]:
        X, scale = _features(s, t0, h, self._industry_code(industry))
        return self.models["in"].predict(X) * scale, self.models["out"].predict(X) * scale

    def _components(self, history: History, horizon: int):
        """Точечный прогноз и блоки остатков (в долях масштаба) или None."""
        s = _Series(history)
        n = len(history)
        h = np.arange(1, horizon + 1)
        mu_in, mu_out = self._predict(s, np.full(horizon, n - 1), h, history.industry)
        # Блоки остатков: та же модель на прошлых точках старта, где факт известен.
        starts = [n - 1 - horizon - BLOCK_STEP * k for k in range(MAX_BLOCKS)]
        starts = [t for t in starts if t >= MIN_HISTORY - 1 and not history.missing[t - MIN_HISTORY + 1 : t + horizon + 1].any()]
        if len(starts) < MIN_BLOCKS:
            return None
        t0 = np.repeat(starts, horizon)
        hh = np.tile(h, len(starts))
        p_in, p_out = self._predict(s, t0, hh, history.industry)
        scale_then = (p_in + p_out).reshape(len(starts), horizon).mean(axis=1, keepdims=True) + 1.0
        r_in = (s.inflow[t0 + hh] - p_in).reshape(len(starts), horizon) / scale_then
        r_out = (s.outflow[t0 + hh] - p_out).reshape(len(starts), horizon) / scale_then
        scale = mu_in.mean() + mu_out.mean() + 1.0
        # Средний остаток блоков — поправка на смещение модели для этой компании:
        # переносим её в точечный прогноз, а множитель разброса применяем только
        # к отклонениям, чтобы калибровка ширины не раздувала смещение.
        mu_in, mu_out = mu_in + r_in.mean(axis=0) * scale, mu_out + r_out.mean(axis=0) * scale
        return mu_in, mu_out, r_in - r_in.mean(axis=0), r_out - r_out.mean(axis=0), scale

    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths:
        if not self.ready:
            raise NotTrainedError("gbm_global is not trained: run training or load artifacts")
        if horizon > MAX_HORIZON or len(history) < MIN_HISTORY:
            return SeasonalNaive().forecast(history, horizon, n_paths, rng)
        c = self._components(history, horizon)
        if c is None:
            # Мало истории для блоков: уровень от модели, разброс от naive.
            s = _Series(history)
            mu_in, mu_out = self._predict(s, np.full(horizon, len(history) - 1), np.arange(1, horizon + 1), history.industry)
            naive = SeasonalNaive().forecast(history, horizon, n_paths, rng)
            inflow, outflow = _nonneg(mu_in + naive.inflow - naive.inflow.mean(axis=0),
                                      mu_out + naive.outflow - naive.outflow.mean(axis=0))
            return Paths(inflow, outflow, low_confidence=True)
        mu_in, mu_out, r_in, r_out, scale = c
        k = rng.integers(len(r_in), size=n_paths)
        inflow, outflow = _nonneg(mu_in + self.spread * r_in[k] * scale, mu_out + self.spread * r_out[k] * scale)
        return Paths(inflow, outflow, low_confidence=history.valid_days < MIN_CONFIDENT_DAYS)


def _nonneg(inflow: np.ndarray, outflow: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Убирает отрицательные потоки, перенося их в противоположный: чистый
    поток (от него зависит остаток) сохраняется точно, медиана не смещается."""
    neg_in, neg_out = np.minimum(inflow, 0), np.minimum(outflow, 0)
    return inflow - neg_in - neg_out, outflow - neg_out - neg_in


def _train_origins(h: History) -> np.ndarray:
    n = len(h)
    out = []
    for t0 in range(MIN_HISTORY - 1, n - 1 - MAX_HORIZON, TRAIN_STEP):
        if not h.missing[t0 - MIN_HISTORY + 1 : t0 + MAX_HORIZON + 1].any():
            out.append(t0)
    return np.array(out, dtype=int)


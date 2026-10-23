"""Бэктест прогнозных моделей на датасете кейса.

Скользящие точки старта — как в Go (`backend/cmd/backtest`): для каждой
компании 6 точек с шагом 30 дней от конца истории, горизонт 30 дней, в
окне [as_of − min_history, as_of + horizon] нет пропусков выписки.

Честность для глобальных моделей: для каждой точки старта модель обучена
только на данных до неё (переобучение раз в месяц, как в проде; --once —
одно обучение на самой ранней дате) и без отложенных компаний (unseen).
У всех моделей один и тот же набор точек старта.

    python -m zavozik_ml.eval.backtest --models seasonal_naive,ets,gbm_global

Метрики:
  * MAE / WAPE остатка на горизонтах 7/14/30 по медиане (p50);
  * coverage — доля факта внутри коридора p10–p90 (идеал 80%);
  * pinball — средний pinball-loss по квантилям 0.1/0.5/0.9, нормированный
    на средний |остаток| (качество всего распределения, меньше — лучше);
  * разрывы: событие — «остаток без докачки владельцем» уходит ниже нуля на
    горизонте (факт минус займы учредителя и переводы своих средств после
    as_of: именно ими в данных закрывают разрывы). Прогноз разрыва —
    P(минимум остатка < 0) >= gap_threshold. Precision, recall, Brier и
    lead — за сколько дней до события мы его увидели.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from zavozik_ml import forecasters
from zavozik_ml.data import DEFAULT_FLOWS, Company, load_companies
from zavozik_ml.forecasters import models  # noqa: F401 — регистрирует все модели

QUANTILES = (0.1, 0.5, 0.9)
BASELINE = "seasonal_naive"
REPORT_HORIZONS = (7, 14, 30)


@dataclass(frozen=True)
class Config:
    horizon: int = 30
    origins: int = 6
    step: int = 30
    min_history: int = 56
    n_paths: int = 200
    gap_threshold: float = 0.3
    holdout_share: float = 0.2  # доля компаний, которых глобальная модель не видит
    seed: int = 42


@dataclass(frozen=True)
class Origin:
    company: Company
    o: int  # индекс дня as_of

    @property
    def as_of(self) -> date:
        return self.company.history.dates[self.o]


def make_origins(c: Company, cfg: Config) -> list[Origin]:
    h = c.history
    n = len(h)
    out = []
    for k in range(cfg.origins):
        end = n - 1 - k * cfg.step
        o = end - cfg.horizon
        if o < cfg.min_history:
            continue
        win = slice(o - cfg.min_history + 1, end + 1)
        if h.missing[win].any() or np.isnan(c.balance[win]).any():
            continue
        out.append(Origin(c, o))
    return out


def split(companies: list[Company], cfg: Config) -> tuple[list[Origin], list[date], set[str]]:
    """Точки старта для оценки, даты переобучения и отложенные компании.

    Даты переобучения — точки старта основной когорты (компании, живые в
    последний месяц): глобальная модель для точки старта обучена на данных
    не позже ближайшей предыдущей такой даты, как при ежемесячном обновлении.
    """
    origins = [o for c in companies for o in make_origins(c, cfg)]
    last = max(c.history.dates[-1] for c in companies)
    # Основная когорта — компании, живые в последний месяц; по ним cutoff.
    cohort = [o for o in origins if (last - o.company.history.dates[-1]).days <= 31]
    # Переобучение раз в месяц: первое число каждого месяца с точками старта.
    cutoffs = sorted({o.as_of.replace(day=1) for o in cohort})
    first = min(o.as_of for o in cohort)
    origins = [o for o in origins if o.as_of >= first]
    rng = np.random.default_rng(cfg.seed)
    ids = sorted(c.id for c in companies)
    holdout = set(rng.choice(ids, size=int(len(ids) * cfg.holdout_share), replace=False))
    return origins, cutoffs, holdout


def train_histories(companies: list[Company], cutoff: date, holdout: set[str]) -> list[forecasters.History]:
    out = []
    for c in companies:
        if c.id in holdout:
            continue
        n = sum(1 for d in c.history.dates if d <= cutoff)
        if n > 0:
            out.append(c.history.head(n))
    return out


def evaluate_origin(model: forecasters.Forecaster, org: Origin, cfg: Config, rng: np.random.Generator) -> dict:
    c, o, hz = org.company, org.o, cfg.horizon
    paths = model.forecast(c.history.head(o + 1), hz, cfg.n_paths, rng)
    bal = c.balance[o] + np.cumsum(paths.inflow - paths.outflow, axis=1)  # (paths, hz)
    actual = c.balance[o + 1 : o + hz + 1]
    # Остаток без докачки владельцем: убираем внутренние движения после as_of.
    adjusted = actual - np.cumsum(c.internal_net()[o + 1 : o + hz + 1])
    q = np.quantile(bal, QUANTILES, axis=0)

    gap_prob = float((bal.min(axis=1) < 0).mean())
    below = np.flatnonzero(adjusted < 0)
    return {
        "model": model.name,
        "company_id": c.id,
        "industry": c.history.industry,
        "as_of": org.as_of,
        "low_confidence": paths.low_confidence,
        "actual": actual,
        "adjusted": adjusted,
        "q": q,
        "mae_run": float(np.abs(actual - q[1]).mean()),
        "gap_prob": gap_prob,
        "gap_true": below.size > 0,
        "gap_day": int(below[0]) + 1 if below.size else None,
        "pred_gap_day": _first_day_below(bal, cfg.gap_threshold),
    }


def _first_day_below(bal: np.ndarray, threshold: float) -> int | None:
    """Первый день, где доля путей ниже нуля >= threshold."""
    share = (bal < 0).mean(axis=0)
    idx = np.flatnonzero(share >= threshold)
    return int(idx[0]) + 1 if idx.size else None


def pinball(actual: np.ndarray, q: np.ndarray) -> float:
    loss = 0.0
    for i, tau in enumerate(QUANTILES):
        diff = actual - q[i]
        loss += np.mean(np.maximum(tau * diff, (tau - 1) * diff))
    return loss / len(QUANTILES)


def summarize(results: list[dict], cfg: Config, holdout: set[str]) -> pd.DataFrame:
    rows = []
    df = pd.DataFrame(results)
    # Относительная ошибка к бейзлайну на том же прогоне: не зависит от размера
    # компании, в отличие от WAPE, где доминируют крупные.
    base = df[df.model == BASELINE].set_index(["company_id", "as_of"])["mae_run"]
    if len(base):
        ref = base.reindex(pd.MultiIndex.from_frame(df[["company_id", "as_of"]])).to_numpy()
        df["rel_mae"] = df["mae_run"].to_numpy() / np.maximum(ref, 1.0)
    for (model, part), g in df.groupby([df["model"], df["company_id"].isin(holdout).map({True: "unseen", False: "seen"})]):
        rows.append({"model": model, "companies": part, **_metrics(g, cfg)})
    for model, g in df.groupby("model"):
        rows.append({"model": model, "companies": "all", **_metrics(g, cfg)})
    return pd.DataFrame(rows).sort_values(["companies", "model"]).reset_index(drop=True)


def _metrics(g: pd.DataFrame, cfg: Config) -> dict:
    m: dict = {"runs": len(g)}
    act = np.stack(g["actual"].to_numpy())  # (runs, hz)
    q = np.stack(g["q"].to_numpy())  # (runs, 3, hz)
    for h in REPORT_HORIZONS:
        if h > cfg.horizon:
            continue
        err = np.abs(act[:, h - 1] - q[:, 1, h - 1])
        m[f"mae_{h}"] = err.mean()
        m[f"wape_{h}"] = err.sum() / np.abs(act[:, h - 1]).sum()
    m["coverage"] = ((act >= q[:, 0]) & (act <= q[:, 2])).mean()
    m["pinball"] = np.mean([pinball(a, qq) for a, qq in zip(act, q)]) / np.abs(act).mean()
    # То же против остатка бизнеса (без переводов владельца после as_of).
    adj = np.stack(g["adjusted"].to_numpy())
    for h in REPORT_HORIZONS:
        if h <= cfg.horizon:
            err = np.abs(adj[:, h - 1] - q[:, 1, h - 1])
            m[f"biz_wape_{h}"] = err.sum() / np.abs(adj[:, h - 1]).sum()
    m["biz_coverage"] = ((adj >= q[:, 0]) & (adj <= q[:, 2])).mean()
    m["biz_pinball"] = np.mean([pinball(a, qq) for a, qq in zip(adj, q)]) / np.abs(adj).mean()

    true = g["gap_true"].to_numpy(bool)
    prob = g["gap_prob"].to_numpy(float)
    pred = prob >= cfg.gap_threshold
    tp = (pred & true).sum()
    m["gap_events"] = int(true.sum())
    m["gap_precision"] = tp / pred.sum() if pred.sum() else np.nan
    m["gap_recall"] = tp / true.sum() if true.sum() else np.nan
    m["gap_brier"] = np.mean((prob - true) ** 2)
    hit = g[pred & true]
    m["gap_lead_days"] = hit["gap_day"].mean() if len(hit) else np.nan
    m["gap_auc"] = _auc(prob, true)
    if "rel_mae" in g:
        rel = g["rel_mae"].to_numpy(float)
        m["rel_mae_gmean"] = float(np.exp(np.mean(np.log(np.maximum(rel, 1e-6)))))
        m["win_rate"] = float((rel < 1).mean())
    return m


def _auc(score: np.ndarray, label: np.ndarray) -> float:
    """ROC AUC через ранги (вероятность, что разрыв получит больший score)."""
    pos, neg = label.sum(), (~label).sum()
    if pos == 0 or neg == 0:
        return np.nan
    ranks = pd.Series(score).rank().to_numpy()
    return float((ranks[label].sum() - pos * (pos + 1) / 2) / (pos * neg))


def run(
    model_names: list[str], flows: Path, cfg: Config, artifacts: Path | None, rolling: bool = True
) -> tuple[pd.DataFrame, list[dict]]:
    companies = load_companies(flows)
    origins, cutoffs, holdout = split(companies, cfg)
    if not rolling:
        cutoffs = cutoffs[:1]
    print(f"companies: {len(companies)}, origins: {len(origins)}, retrain dates: {[str(c) for c in cutoffs]}, holdout: {len(holdout)}")
    models = [forecasters.get(n) for n in model_names]
    timing = {m.name: [0.0, 0.0] for m in models}
    rngs = {m.name: np.random.default_rng(cfg.seed) for m in models}
    results = []
    # Снаружи — даты переобучения: на каждой сначала обучаем глобальные модели
    # только на прошлом, затем все модели (в т.ч. ансамбли поверх глобальных)
    # прогнозируют точки старта до следующей даты.
    for i, cutoff in enumerate(cutoffs):
        nxt = cutoffs[i + 1] if i + 1 < len(cutoffs) else date.max
        batch = [o for o in origins if (i == 0 or o.as_of >= cutoff) and o.as_of < nxt]
        if not batch:
            continue
        train = None
        for m in models:
            if m.is_global:
                t0 = time.perf_counter()
                train = train or train_histories(companies, cutoff, holdout)
                m.fit(train)
                timing[m.name][0] += time.perf_counter() - t0
        for m in models:
            t0 = time.perf_counter()
            results.extend(evaluate_origin(m, org, cfg, rngs[m.name]) for org in batch)
            timing[m.name][1] += time.perf_counter() - t0
    for m in models:
        if m.is_global and artifacts:
            m.save(artifacts / m.name)
        print(f"{m.name:16s} fit {timing[m.name][0]:6.1f}s  predict {timing[m.name][1]:6.1f}s")
    return summarize(results, cfg, holdout), results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default="seasonal_naive,ets,gbm_global")
    p.add_argument("--flows", type=Path, default=DEFAULT_FLOWS)
    p.add_argument("--out", type=Path, default=DEFAULT_FLOWS.parent / "backtest_py.parquet")
    p.add_argument("--artifacts", type=Path, default=None, help="сохранить обученные глобальные модели сюда")
    p.add_argument("--paths", type=int, default=Config.n_paths)
    p.add_argument("--once", action="store_true", help="обучить глобальные модели один раз на первой дате (без переобучения)")
    args = p.parse_args()

    cfg = Config(n_paths=args.paths)
    summary, results = run(args.models.split(","), args.flows, cfg, args.artifacts, rolling=not args.once)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    cols = ["model", "companies", "runs", *[f"wape_{h}" for h in REPORT_HORIZONS], "coverage",
            *[f"biz_wape_{h}" for h in REPORT_HORIZONS], "biz_coverage", "biz_pinball",
            "rel_mae_gmean", "win_rate", "gap_precision", "gap_recall", "gap_brier", "gap_auc", "gap_lead_days"]
    print(summary[[c for c in cols if c in summary]].round(3).to_string(index=False))

    flat = pd.DataFrame(
        [
            {k: r[k] for k in ("model", "company_id", "industry", "as_of", "low_confidence", "gap_prob", "gap_true", "gap_day")}
            | {"h": h + 1, "actual": r["actual"][h], "adjusted": r["adjusted"][h], "p10": r["q"][0, h], "p50": r["q"][1, h], "p90": r["q"][2, h]}
            for r in results
            for h in range(cfg.horizon)
        ]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    flat.to_parquet(args.out, index=False)
    summary.to_csv(args.out.with_suffix(".summary.csv"), index=False)
    print(f"results: {args.out}")


if __name__ == "__main__":
    main()

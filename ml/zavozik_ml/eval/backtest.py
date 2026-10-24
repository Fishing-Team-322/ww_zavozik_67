"""Бэктест прогнозных моделей на датасете кейса.

Скользящие точки старта — как в Go (`backend/cmd/backtest`): для каждой
компании 6 точек с шагом 30 дней от конца истории, горизонт 30 дней, в
будущий эталон известен, а неполная история проверяется отдельными сегментами.

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
    хотя бы один день с P(остаток < 0) >= gap_threshold. Precision, recall, Brier и
    lead — за сколько дней до события мы его увидели.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from zavozik_ml import forecasters
from zavozik_ml.data import DEFAULT_FLOWS, Company, load_companies
from zavozik_ml.forecasters import models  # noqa: F401 — регистрирует все модели

QUANTILES = (0.1, 0.5, 0.9)
BASELINE = "seasonal_naive"
REPORT_HORIZONS = (7, 14, 30)


class AutoPolicy(forecasters.Forecaster):
    name = "auto"
    description = "Serving auto policy with explicit out-of-domain fallback"

    def forecast(self, history, horizon, n_paths, rng):
        from zavozik_ml.forecasters.base import domain_warnings, select_model
        paths = select_model("auto", history).forecast(history, horizon, n_paths, rng)
        return replace(paths, low_confidence=paths.low_confidence or bool(domain_warnings(history)))


@dataclass(frozen=True)
class Config:
    horizon: int = 30
    origins: int = 6
    step: int = 30
    min_history: int = 7
    n_paths: int = 200
    gap_threshold: float = 0.1  # daily probability, same as Go risk.FindGaps
    holdout_share: float = 0.2  # доля компаний, которых глобальная модель не видит
    seed: int = 42
    scenarios: tuple[str, ...] = ("standard",)


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
        if o + 1 < cfg.min_history:
            continue
        # Не исключаем сложную историю. Но неизвестный будущий факт не
        # является эталоном, а неизвестный начальный баланс нельзя угадать.
        win = slice(o + 1, end + 1)
        if h.missing[win].any() or not np.isfinite(c.balance[o:end+1]).all():
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
    if not origins:
        raise ValueError("no evaluable origins: need known opening balance and future observations")
    last = max(c.history.dates[-1] for c in companies)
    # Основная когорта — компании, живые в последний месяц; по ним cutoff.
    cohort = [o for o in origins if (last - o.company.history.dates[-1]).days <= 31]
    cohort = cohort or origins
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


def stress_history(history: forecasters.History, scenario: str) -> forecasters.History:
    """Меняет только доступный вход; будущий эталон остаётся прежним."""
    if scenario == "standard":
        return history
    if scenario.startswith("short_"):
        n = int(scenario.split("_")[1])
        return replace(history, dates=history.dates[-n:], inflow=history.inflow[-n:],
                       outflow=history.outflow[-n:], missing=history.missing[-n:],
                       categories={k: v[-n:] for k, v in history.categories.items()},
                       missing_known_on=None)
    missing = history.missing.copy()
    if scenario == "gap_14":
        missing[max(0, len(history)-21):max(0, len(history)-7)] = True
    elif scenario == "missing_30pct":
        missing |= np.random.default_rng(723).random(len(history)) < .3
    else:
        raise ValueError(f"unknown stress scenario: {scenario}")
    return replace(history, missing=missing, missing_known_on=None,
                   inflow=np.where(missing, 0, history.inflow), outflow=np.where(missing, 0, history.outflow),
                   categories={k: np.where(missing, 0, v) for k, v in history.categories.items()})


def evaluate_origin(model: forecasters.Forecaster, org: Origin, cfg: Config, rng: np.random.Generator,
                    scenario: str = "standard") -> dict:
    c, o, hz = org.company, org.o, cfg.horizon
    history = stress_history(c.history.head(o + 1), scenario)
    paths = model.forecast(history, hz, cfg.n_paths, rng)
    bal = c.balance[o] + np.cumsum(paths.inflow - paths.outflow, axis=1)  # (paths, hz)
    actual = c.balance[o + 1 : o + hz + 1]
    # Остаток без докачки владельцем: убираем внутренние движения после as_of.
    adjusted = actual - np.cumsum(c.internal_net()[o + 1 : o + hz + 1])
    q = np.quantile(bal, QUANTILES, axis=0)

    gap_prob = float((bal.min(axis=1) < 0).mean())
    below = np.flatnonzero(adjusted < 0)
    account_below = np.flatnonzero(actual < 0)
    predicted_day = _first_day_below(bal, cfg.gap_threshold)
    shortfall = max(0.0, -float(q[1].min()))
    return {
        "model": model.name,
        "scenario": scenario,
        "company_id": c.id,
        "industry": c.history.industry,
        "as_of": org.as_of,
        "low_confidence": paths.low_confidence,
        "actual": actual,
        "adjusted": adjusted,
        "q": q,
        "mae_run": float(np.abs(actual - q[1]).mean()),
        "gap_prob": gap_prob,
        "daily_gap_prob": (bal < 0).mean(axis=0),
        "gap_true": below.size > 0,
        "gap_day": int(below[0]) + 1 if below.size else None,
        "pred_gap_day": predicted_day,
        "gap_alarm": predicted_day is not None,
        "pred_shortfall": shortfall,
        "actual_shortfall": max(0.0, -float(adjusted.min())),
        "account_shortfall": max(0.0, -float(actual.min())),
        "account_gap_true": account_below.size > 0,
        "account_gap_day": int(account_below[0]) + 1 if account_below.size else None,
        "opening_negative": bool(c.balance[o] < 0),
        "history_days": len(history),
        "missing_share": float(history.missing[-91:].mean()),
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
    scenarios = sorted({r.get("scenario", "standard") for r in results})
    if len(scenarios) > 1:
        return pd.concat([summarize([r for r in results if r["scenario"] == s], cfg, holdout)
                          for s in scenarios], ignore_index=True)
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
    return pd.DataFrame(rows).assign(scenario=scenarios[0]).sort_values(["companies", "model"]).reset_index(drop=True)


def _metrics(g: pd.DataFrame, cfg: Config) -> dict:
    m: dict = {"runs": len(g)}
    act = np.stack(g["actual"].to_numpy())  # (runs, hz)
    q = np.stack(g["q"].to_numpy())  # (runs, 3, hz)
    for h in REPORT_HORIZONS:
        if h > cfg.horizon:
            continue
        err = np.abs(act[:, h - 1] - q[:, 1, h - 1])
        m[f"mae_{h}"] = err.mean()
        m[f"wape_{h}"] = safe_ratio(err.sum(), np.abs(act[:, h - 1]).sum())
    m["coverage"] = ((act >= q[:, 0]) & (act <= q[:, 2])).mean()
    m["pinball"] = safe_ratio(np.mean([pinball(a, qq) for a, qq in zip(act, q)]), np.abs(act).mean())
    # То же против остатка бизнеса (без переводов владельца после as_of).
    adj = np.stack(g["adjusted"].to_numpy())
    for h in REPORT_HORIZONS:
        if h <= cfg.horizon:
            err = np.abs(adj[:, h - 1] - q[:, 1, h - 1])
            m[f"biz_wape_{h}"] = safe_ratio(err.sum(), np.abs(adj[:, h - 1]).sum())
    m["biz_coverage"] = ((adj >= q[:, 0]) & (adj <= q[:, 2])).mean()
    m["biz_pinball"] = safe_ratio(np.mean([pinball(a, qq) for a, qq in zip(adj, q)]), np.abs(adj).mean())

    true = g["gap_true"].to_numpy(bool)
    prob = g["gap_prob"].to_numpy(float)
    pred = g["gap_alarm"].to_numpy(bool)
    tp = (pred & true).sum()
    m["gap_events"] = int(true.sum())
    m["gap_precision"] = tp / pred.sum() if pred.sum() else np.nan
    m["gap_recall"] = tp / true.sum() if true.sum() else np.nan
    m["gap_brier"] = np.mean((prob - true) ** 2)
    hit = g[pred & true]
    m["gap_lead_days"] = hit["gap_day"].mean() if len(hit) else np.nan
    m["gap_auc"] = _auc(prob, true)
    m["gap_alerts"] = int(pred.sum())
    m["gap_false_alerts"] = int((pred & ~true).sum())
    m["gap_false_alert_rate"] = safe_ratio((pred & ~true).sum(), (~true).sum())
    # Дата и сумма оцениваются отдельно от заблаговременности.
    m["gap_date_mae_days"] = float((hit["pred_gap_day"] - hit["gap_day"]).abs().mean()) if len(hit) else np.nan
    m["gap_shortfall_mae"] = float((g.loc[true, "pred_shortfall"]-g.loc[true, "actual_shortfall"]).abs().mean()) if true.any() else np.nan
    m["gap_ece"] = calibration_error(prob, true)
    if "daily_gap_prob" in g:
        daily = np.stack(g["daily_gap_prob"].to_numpy())
        m["daily_gap_brier"] = float(np.mean((daily-(adj < 0))**2))
        m["daily_gap_ece"] = calibration_error(daily.ravel(), (adj < 0).ravel())
    account = g["account_gap_true"].to_numpy(bool)
    m["account_gap_events"] = int(account.sum())
    m["account_gap_precision"] = safe_ratio((pred & account).sum(), pred.sum())
    m["account_gap_recall"] = safe_ratio((pred & account).sum(), account.sum())
    m["account_gap_brier"] = float(np.mean((prob-account)**2))
    m["opening_negative_runs"] = int(g["opening_negative"].sum())
    eligible = ~g["opening_negative"].to_numpy(bool)
    m["new_gap_events"] = int((true & eligible).sum())
    m["new_gap_recall"] = safe_ratio((pred & true & eligible).sum(), (true & eligible).sum())
    m["low_confidence_share"] = float(g["low_confidence"].mean())
    for label, target in (("account", act), ("business", adj)):
        m[f"{label}_path_wape"] = safe_ratio(np.abs(target-q[:,1]).sum(), np.abs(target).sum())
        m[f"{label}_path_mae"] = float(np.abs(target-q[:,1]).mean())
    if "rel_mae" in g:
        rel = g["rel_mae"].to_numpy(float)
        m["rel_mae_gmean"] = float(np.exp(np.mean(np.log(np.maximum(rel, 1e-6)))))
        m["win_rate"] = float((rel < 1).mean())
    return m


def safe_ratio(numerator, denominator) -> float:
    return float(numerator / denominator) if denominator > 0 else float("nan")


def calibration_error(prob: np.ndarray, truth: np.ndarray) -> float:
    """ECE для вероятности события на горизонте; не вероятность одного дня."""
    edges = np.linspace(0, 1, 6)
    total = 0.0
    for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        mask = (prob >= lo) & ((prob <= hi) if i == 4 else (prob < hi))
        if mask.any():
            total += mask.mean()*abs(prob[mask].mean()-truth[mask].mean())
    return float(total)


def _auc(score: np.ndarray, label: np.ndarray) -> float:
    """ROC AUC через ранги (вероятность, что разрыв получит больший score)."""
    pos, neg = label.sum(), (~label).sum()
    if pos == 0 or neg == 0:
        return np.nan
    ranks = pd.Series(score).rank().to_numpy()
    return float((ranks[label].sum() - pos * (pos + 1) / 2) / (pos * neg))


def folds(companies: list[Company], k: int, seed: int) -> list[set[str]]:
    ids = np.array(sorted(c.id for c in companies))
    np.random.default_rng(seed).shuffle(ids)
    return [set(part) for part in np.array_split(ids, k)]


def protocol_origins(origins: list[Origin], cfg: Config, protocol: str, spec: dict) -> list[Origin]:
    """Versioned time boundary; v1 is retained solely for historical reproducibility.

    In v2 every development target must precede audit_start, not merely its
    forecast origin. Company membership and audit selection are unchanged.
    """
    version = spec.get("version")
    if version not in (1, 2):
        raise ValueError(f"unsupported evaluation split version: {version}")
    if version == 2 and spec.get("development_target_policy") != "all_target_dates_before_audit_start":
        raise ValueError("unsupported development target policy for split v2")
    boundary = date.fromisoformat(spec["audit_start"])
    holdout = set(spec["audit_companies"])
    if protocol == "audit":
        return [o for o in origins if o.company.id in holdout and o.as_of >= boundary]
    if protocol != "development":
        raise ValueError(f"unsupported evaluation protocol: {protocol}")
    return [o for o in origins if o.company.id not in holdout and
            o.as_of + timedelta(days=cfg.horizon if version == 2 else 0) < boundary]


def run(
    model_names: list[str], flows: Path, cfg: Config, artifacts: Path | None, rolling: bool = True, cv: int = 0,
    protocol: str = "exploratory", split_path: Path | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    """cv > 0 — кросс-валидация по компаниям: каждая группа по очереди отложена,
    глобальные модели учатся без неё и оцениваются только на ней — все
    компании оказываются «новыми», как в проверке экспертов на своём наборе."""
    companies = load_companies(flows)
    origins, cutoffs, holdout = split(companies, cfg)
    if protocol != "exploratory":
        spec = json.loads(split_path.read_text())
        holdout = set(spec["audit_companies"])
        origins = protocol_origins(origins, cfg, protocol, spec)
        # Ни в разработке, ни в итоговой оценке аудит-компании не участвуют в fit.
        companies = [c for c in companies if c.id not in holdout]
        cutoffs = sorted({o.as_of.replace(day=1) for o in origins})
        if protocol == "audit":
            cv = 0
    if not origins:
        raise ValueError("no evaluable origins for this protocol")
    if not rolling:
        cutoffs = cutoffs[:1]
    groups = folds(companies, cv, cfg.seed) if cv else [holdout]
    if cv:
        holdout = {c.id for c in companies}
    print(f"companies: {len(companies)}, origins: {len(origins)}, retrain dates: {[str(c) for c in cutoffs]}, "
          f"{'cv folds: ' + str(cv) if cv else 'holdout: ' + str(len(holdout))}")
    # Ensemble depends on a trained GBM, even if the caller requests only ensemble.
    if any(n in model_names for n in ("ensemble", "auto")) and "gbm_global" not in model_names:
        model_names = ["gbm_global", *model_names]
    models = [AutoPolicy() if n == "auto" else forecasters.get(n) for n in model_names]
    timing = {m.name: [0.0, 0.0] for m in models}
    results = []
    # Снаружи — даты переобучения: на каждой сначала обучаем глобальные модели
    # только на прошлом, затем все модели (в т.ч. ансамбли поверх глобальных)
    # прогнозируют точки старта до следующей даты.
    for fold_number, excluded in enumerate(groups, 1):
        scope = [o for o in origins if o.company.id in excluded] if cv else origins
        for i, cutoff in enumerate(cutoffs):
            nxt = cutoffs[i + 1] if i + 1 < len(cutoffs) else date.max
            batch = [o for o in scope if (i == 0 or o.as_of >= cutoff) and o.as_of < nxt]
            if not batch:
                continue
            print(f"fold {fold_number}/{len(groups)} cutoff {cutoff}: {len(batch)} origins", flush=True)
            train = None
            for m in models:
                if m.is_global:
                    t0 = time.perf_counter()
                    train = train or train_histories(companies, cutoff, excluded)
                    m.fit(train)
                    timing[m.name][0] += time.perf_counter() - t0
            for m in models:
                t0 = time.perf_counter()
                for org in batch:
                    # Стабильный seed: порядок моделей/компаний/сценариев не меняет результат.
                    key = f"{cfg.seed}:{m.name}:{org.company.id}:{org.as_of}"
                    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "little")
                    for scenario in cfg.scenarios:
                        results.append(evaluate_origin(m, org, cfg, np.random.default_rng(seed), scenario))
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
    p.add_argument("--cv", type=int, default=3, help="кросс-валидация по компаниям; в audit выключена")
    p.add_argument("--protocol", choices=["development", "audit", "exploratory"], default="development")
    p.add_argument("--split", type=Path, default=Path(__file__).resolve().parents[2] / "eval" / "split_v2.json",
                   help="v2 purges development targets crossing audit_start; v1 is historical only")
    p.add_argument("--gap-threshold", type=float, default=0.1)
    p.add_argument("--scenarios", default="standard", help="comma-separated: standard,short_14,short_28,short_56,gap_14,missing_30pct")
    p.add_argument("--ensemble-shares", default="", help="development-only comparison of additional GBM path shares, e.g. .25,.75,.9")
    p.add_argument("--short-global", action="store_true", help="development-only experiment: global level for histories >=14 days")
    p.add_argument("--legacy-short-naive", action="store_true", help="development-only ablation of global level on short histories")
    args = p.parse_args()
    if args.legacy_short_naive:
        if args.protocol != "development":
            p.error("short-history ablation is allowed only on development data")
        forecasters.get("gbm_global").short_history_global = False
    if args.short_global:
        if args.protocol != "development":
            p.error("short-history experiment is allowed only on development data")
        forecasters.get("gbm_global").short_history_global = True
    if args.ensemble_shares:
        if args.protocol != "development":
            p.error("ensemble share search is allowed only on development data")
        from zavozik_ml.forecasters.ensemble import Ensemble
        for raw in args.ensemble_shares.split(","):
            share = float(raw)
            if not 0 < share < 1:
                p.error("ensemble shares must be in (0, 1)")
            name = f"ensemble_{round(share*100)}"
            candidate = type(name, (Ensemble,), {"name": name, "share": share})
            forecasters.register(candidate)
            args.models += "," + name

    from zavozik_ml.provenance import source_fingerprint
    source_hash = source_fingerprint()
    cfg = Config(n_paths=args.paths, gap_threshold=args.gap_threshold, scenarios=tuple(args.scenarios.split(",")))
    if not 0 < cfg.gap_threshold <= 1 or cfg.n_paths < 1:
        p.error("gap threshold must be in (0, 1], paths must be positive")
    summary, results = run(args.models.split(","), args.flows, cfg, args.artifacts, rolling=not args.once,
                           cv=args.cv, protocol=args.protocol, split_path=args.split)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    cols = ["scenario", "model", "companies", "runs", *[f"wape_{h}" for h in REPORT_HORIZONS], "coverage",
            *[f"biz_wape_{h}" for h in REPORT_HORIZONS], "biz_coverage", "biz_pinball",
            "rel_mae_gmean", "win_rate", "gap_precision", "gap_recall", "gap_brier", "gap_auc", "gap_lead_days"]
    print(summary[[c for c in cols if c in summary]].round(3).to_string(index=False))

    flat = pd.DataFrame(
        [
            {k: v for k, v in r.items() if k not in ("actual", "adjusted", "q", "daily_gap_prob")}
            | {"h": h + 1, "actual": r["actual"][h], "adjusted": r["adjusted"][h], "p10": r["q"][0, h], "p50": r["q"][1, h], "p90": r["q"][2, h], "daily_gap_prob": r["daily_gap_prob"][h]}
            for r in results
            for h in range(cfg.horizon)
        ]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    flat.to_parquet(args.out, index=False)
    summary.to_csv(args.out.with_suffix(".summary.csv"), index=False)
    metadata = {
        "protocol": args.protocol, "cv": args.cv if args.protocol != "audit" else 0,
        "flow_scope": "business_without_internal_transfers_including_recurring",
        "alarm_policy": "first daily probability below zero >= threshold", "gap_threshold": cfg.gap_threshold,
        "horizon": cfg.horizon, "paths": cfg.n_paths, "seed": cfg.seed,
        "source_sha256_at_start": source_hash, "source_changed_during_run": source_hash != source_fingerprint(),
        "scenarios": cfg.scenarios, "rolling": not args.once,
        "ensemble_shares": args.ensemble_shares,
        "short_global": forecasters.get("gbm_global").short_history_global,
        "flows_sha256": hashlib.sha256(args.flows.read_bytes()).hexdigest(),
        "split": json.loads(args.split.read_text()) if args.protocol != "exploratory" else None,
        "limitation": "All source companies previously inspected by Claude; internal locked audit, not an independent external test.",
    }
    args.out.with_suffix(".metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    # Сегменты истории и калибровочная таблица нужны даже при плохом результате.
    per_run = pd.DataFrame([r for r in results if r["scenario"] == "standard"])
    if per_run.empty:
        print(f"results: {args.out}; no standard scenario for segment report")
        return
    segmented = []
    for name, mask in {
        "short_under_90d": per_run.history_days < 90,
        "history_with_gaps": per_run.missing_share > 0,
        "long_clean_history": (per_run.history_days >= 90) & (per_run.missing_share == 0),
    }.items():
        for model, group in per_run[mask].groupby("model"):
            segmented.append({"segment": name, "model": model, **_metrics(group, cfg)})
    pd.DataFrame(segmented).to_csv(args.out.with_suffix(".segments.csv"), index=False)
    calibration = []
    for model, group in per_run.groupby("model"):
        for lo in np.arange(0, 1, .2):
            mask = (group.gap_prob >= lo) & (group.gap_prob <= lo+.2 if lo >= .79 else group.gap_prob < lo+.2)
            z = group[mask]
            calibration.append({"model": model, "lower": lo, "upper": lo+.2, "n": len(z),
                                "mean_prediction": z.gap_prob.mean(), "business_frequency": z.gap_true.mean(),
                                "account_frequency": z.account_gap_true.mean()})
    pd.DataFrame(calibration).to_csv(args.out.with_suffix(".calibration.csv"), index=False)
    print(f"results: {args.out}")


if __name__ == "__main__":
    main()

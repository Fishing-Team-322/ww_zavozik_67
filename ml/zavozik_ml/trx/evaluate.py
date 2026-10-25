"""Бэктест прогноза TrxGPT на компаниях кейса — сравнение с seasonal naive.

    python -m zavozik_ml.trx.evaluate --model runs/finetune/best.pt --shard data/trx/case \\
        --roles audit --min-origin 2026-07-01 --out reports/trx_eval.csv

Точки старта: для каждой компании с шагом --step дней от конца истории,
горизонт --horizon, не раньше --min-origin. Факт — остаток бизнеса
(остаток на счёте в день прогноза + потоки бизнеса без переводов владельца)
из выгрузки Go `ml/data/flows.csv`; та же цель, что у основного бэктеста.

Метрики (как в zavozik_ml.eval.backtest): WAPE остатка на 7/14/30 дней по
медиане путей, покрытие p10–p90, разрыв — остаток бизнеса уходит ниже нуля:
Brier, AUC, точность и полнота при вероятности ≥ 0.3.
Оценивать только моделью, которая эти компании и даты не видела.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from zavozik_ml import calendar as cal

from .dataset import seq_bucket
from .generate import context_tokens, generate
from .shards import Shard
from .train import load_model, pick_device

ML_DIR = Path(__file__).resolve().parents[2]
REPORT_HORIZONS = (7, 14, 30)


def load_flows(path: Path) -> dict[str, pd.DataFrame]:
    df = pd.read_csv(path, usecols=["company_id", "date", "inflow", "outflow", "missing", "balance"],
                     dtype={"company_id": str}, parse_dates=["date"])
    df["day"] = df["date"].values.astype("datetime64[D]").astype(np.int64)
    return {cid: g.sort_values("day").reset_index(drop=True) for cid, g in df.groupby("company_id")}


def naive_paths(flows: pd.DataFrame, o: int, horizon: int, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """Seasonal naive: для каждого рабочего дня — случайный рабочий день с тем же
    днём недели за 8 недель до прогноза. Возвращает чистый поток (paths, H)."""
    hist = flows.iloc[max(0, o - 55) : o + 1]
    hist = hist[~hist["missing"]]
    days = hist["day"].to_numpy()
    work_hist = cal.is_workday(days.astype("datetime64[D]"))
    use_cal = not bool((~work_hist & ((hist["inflow"] + hist["outflow"]).to_numpy() > 0)).any())
    net = (hist["inflow"] - hist["outflow"]).to_numpy()
    wd = (days + 3) % 7
    origin_day = int(flows["day"].iloc[o])
    out = np.zeros((n_paths, horizon))
    for d in range(horizon):
        day = origin_day + d + 1
        if use_cal and not cal.is_workday(np.array([day], dtype="datetime64[D]"))[0]:
            continue
        pool = np.flatnonzero((wd == (day + 3) % 7) & (work_hist if use_cal else True))
        if len(pool):
            out[:, d] = net[rng.choice(pool, size=n_paths)]
    return out


def metrics(rows: list[dict], name: str, threshold: float) -> dict:
    act = np.stack([r["actual"] for r in rows])
    q = np.stack([r[f"{name}_q"] for r in rows])  # (runs, 3, H)
    m = {"model": name, "runs": len(rows)}
    for h in REPORT_HORIZONS:
        if h <= act.shape[1]:
            err = np.abs(act[:, h - 1] - q[:, 1, h - 1])
            m[f"wape_{h}"] = err.sum() / max(np.abs(act[:, h - 1]).sum(), 1.0)
    m["coverage"] = float(((act >= q[:, 0]) & (act <= q[:, 2])).mean())
    true = np.array([r["gap_true"] for r in rows])
    prob = np.array([r[f"{name}_gap_prob"] for r in rows])
    pred = prob >= threshold
    m["gap_events"] = int(true.sum())
    m["gap_precision"] = float((pred & true).sum() / pred.sum()) if pred.sum() else float("nan")
    m["gap_recall"] = float((pred & true).sum() / true.sum()) if true.sum() else float("nan")
    m["gap_brier"] = float(np.mean((prob - true) ** 2))
    if 0 < true.sum() < len(true):
        ranks = pd.Series(prob).rank().to_numpy()
        m["gap_auc"] = float((ranks[true].sum() - true.sum() * (true.sum() + 1) / 2) / (true.sum() * (~true).sum()))
    return m


def select_companies(shard: Shard, flows: dict, roles: set[str], buckets: tuple[int, int] | None,
                     max_companies: int = 0) -> list[tuple[int, str]]:
    seqs = [(i, s["id"]) for i, s in enumerate(shard.sequences)
            if s.get("role") in roles and s["id"] in flows
            and (buckets is None or buckets[0] <= seq_bucket(s["id"]) < buckets[1])]
    return seqs[:max_companies] if max_companies else seqs


def backtest(model, vocab, shard: Shard, flows: dict, seqs: list[tuple[int, str]], min_origin: int, horizon: int,
             step: int, origins: int, paths: int, device, gen_kw: dict | None = None, verbose: bool = True) -> list[dict]:
    """Точки старта по компаниям → пути остатка TrxGPT и naive + факт.

    В строке хранятся сами пути (`trx_bal`, `naive_bal`), чтобы tune_gen.py мог
    смешивать модели без повторной генерации, и итоги приходов/расходов за
    горизонт — для диагностики смещения."""
    remap = np.array([vocab.get(n) for n in shard.vocab.names], dtype=np.int64)
    rng = np.random.default_rng(0)
    rows = []
    for n_done, (si, cid) in enumerate(seqs, 1):
        f = flows[cid]
        n = len(f)
        tok = shard.slice(si)
        for k in range(origins):
            o = n - 1 - horizon - k * step
            if o < 56 or f["day"].iloc[o] < min_origin:
                continue
            win = f.iloc[o : o + horizon + 1]
            if win["missing"].any() or np.isnan(win["balance"].iloc[0]):
                continue
            origin_day = int(f["day"].iloc[o])
            upto = int(np.searchsorted(tok["day"], origin_day, side="right"))
            if upto < 16:
                continue
            ctx = context_tokens({k2: v[:upto] for k2, v in tok.items()}, remap, "case")
            start_balance = float(f["balance"].iloc[o])
            future = f.iloc[o + 1 : o + horizon + 1]
            actual = start_balance + np.cumsum((future["inflow"] - future["outflow"]).to_numpy())

            g = generate(model, ctx, vocab, origin_day, horizon, paths, "case", seed=si * 1000 + k, device=device,
                         **(gen_kw or {}))
            rows.append({
                "company_id": cid, "as_of": str(np.datetime64(origin_day, "D")), "actual": actual,
                "gap_true": bool((actual < 0).any()),
                "trx_bal": start_balance + np.cumsum(g.business_in - g.business_out, axis=1),
                "start": start_balance, "trx_cin": np.cumsum(g.business_in, axis=1),
                "trx_cout": np.cumsum(g.business_out, axis=1),
                "naive_bal": start_balance + np.cumsum(naive_paths(f, o, horizon, paths, rng), axis=1),
                "act_in": float(future["inflow"].sum()), "act_out": float(future["outflow"].sum()),
                "gen_in": float(np.median(g.business_in.sum(1))), "gen_out": float(np.median(g.business_out.sum(1))),
                # Бизнес-потоки компании за 90 дней до прогноза — темп для подгонки (tune_gen).
                "hist_in90": float(f["inflow"].iloc[max(0, o - 89) : o + 1].sum()),
                "hist_out90": float(f["outflow"].iloc[max(0, o - 89) : o + 1].sum()),
                "hist_days": int(min(90, o + 1)),
                "act_ops": int(np.searchsorted(tok["day"], origin_day + horizon, side="right") - upto),
                "trx_ops_per_path": float(g.n_ops.mean()),
            })
        if verbose:
            print(f"[{n_done}/{len(seqs)}] {cid}: точек старта всего {len(rows)}", flush=True)
    return rows


def summarize(rows: list[dict], name: str, threshold: float) -> dict:
    """Метрики по путям остатка `<name>_bal` (квантили и вероятность разрыва — из путей)."""
    for r in rows:
        bal = r[f"{name}_bal"]
        r[f"{name}_q"] = np.quantile(bal, [0.1, 0.5, 0.9], axis=0)
        r[f"{name}_gap_prob"] = float((bal.min(axis=1) < 0).mean())
    return metrics(rows, name, threshold)


def bias(rows: list[dict]) -> dict:
    """Во сколько раз сгенерированное больше факта за горизонт (по сумме точек; 1 — идеально)."""
    s = lambda k: sum(r[k] for r in rows)
    return {"in_ratio": s("gen_in") / max(s("act_in"), 1.0), "out_ratio": s("gen_out") / max(s("act_out"), 1.0),
            "ops_ratio": s("trx_ops_per_path") / max(s("act_ops"), 1)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--shard", type=Path, default=ML_DIR / "data" / "trx" / "case")
    p.add_argument("--flows", type=Path, default=ML_DIR / "data" / "flows.csv")
    p.add_argument("--roles", default="audit")
    p.add_argument("--buckets", default="", help="корзины хеша компаний, например 80-100")
    p.add_argument("--min-origin", default="2026-07-01")
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--step", type=int, default=30)
    p.add_argument("--origins", type=int, default=6)
    p.add_argument("--paths", type=int, default=200)
    p.add_argument("--temperature", type=float, default=1.0)
    p.add_argument("--amount-temp", type=float, default=0, help="температура суммы (0 — как --temperature)")
    p.add_argument("--amount-top-p", type=float, default=1.0)
    p.add_argument("--cap-mult", type=float, default=0, help="потолок суммы: × крупнейшая операция истории (0 — нет)")
    p.add_argument("--history-days", type=int, default=0, help="суммы из истории компании за N дней (0 — модели)")
    p.add_argument("--gap-threshold", type=float, default=0.3)
    p.add_argument("--max-companies", type=int, default=0)
    p.add_argument("--device", default="auto")
    p.add_argument("--out", type=Path, default=ML_DIR / "reports" / "trx_eval.csv")
    args = p.parse_args()

    device = pick_device(args.device)
    model, vocab, _ = load_model(args.model, map_location="cpu")
    model.to(device)
    shard = Shard(args.shard)
    flows = load_flows(args.flows)
    buckets = tuple(int(x) for x in args.buckets.split("-")) if args.buckets else None
    seqs = select_companies(shard, flows, set(args.roles.split(",")), buckets, args.max_companies)
    gen_kw = {"temperature": args.temperature, "amount_temperature": args.amount_temp or None,
              "amount_top_p": args.amount_top_p, "cap_mult": args.cap_mult,
              "history_days": args.history_days}
    rows = backtest(model, vocab, shard, flows, seqs, int(np.datetime64(args.min_origin, "D").astype(np.int64)),
                    args.horizon, args.step, args.origins, args.paths, device, gen_kw)
    if not rows:
        raise SystemExit("нет подходящих точек старта: проверьте --roles и --min-origin")
    summary = pd.DataFrame([summarize(rows, "trx", args.gap_threshold), summarize(rows, "naive", args.gap_threshold)])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.out, index=False)
    pd.set_option("display.width", 200)
    print(summary.round(3).to_string(index=False))
    b = bias(rows)
    print(f"смещение генерации (сгенерировано / факт за горизонт): приходы {b['in_ratio']:.2f}, "
          f"расходы {b['out_ratio']:.2f}, операций {b['ops_ratio']:.2f}; отчёт: {args.out}")


if __name__ == "__main__":
    torch.set_grad_enabled(False)
    main()

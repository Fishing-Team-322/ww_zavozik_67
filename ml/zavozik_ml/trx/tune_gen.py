"""Подбор настроек генерации TrxGPT без переобучения модели.

Что подбирается:
  * сумма: температура, top-p и потолок «× крупнейшая разовая операция
    компании того же направления» — против редких огромных сумм из хвоста;
  * поправка смещения: генерация может систематически занижать приходы и
    завышать расходы (накопление ошибки при пошаговой генерации) — множители
    k_in, k_out подгоняют сгенерированные суммы за горизонт к факту;
  * гибрид по горизонту: путь остатка = w(h)·TrxGPT + (1 − w(h))·naive, где
    w(h) линейно идёт от 1 в первый день до w30 на 30-й (без повторной генерации).

Подбор — только на компаниях разработки `development[80-100]` и только на
датах после отсечки обучения (с 2026-07-01): этих дат модель не видела.
Аудит — один раз в конце, лучшей настройкой, рядом с исходной.

    python -m zavozik_ml.trx.tune_gen --model runs/finetune-v2/final.pt --out runs/gen-tune

Итог — `<out>/best.json` (флаги для evaluate.py и вес гибрида) и `<out>/report.csv`.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .evaluate import ML_DIR, backtest, bias, load_flows, select_companies, summarize
from .shards import Shard
from .train import load_model, pick_device

# (имя, настройки генерации). Первая — как было на этапе 8.
CONFIGS = [
    ("исходная", {}),
    ("потолок 1.5", {"cap_mult": 1.5}),
    ("потолок 1.5 + t 0.8", {"cap_mult": 1.5, "amount_temperature": 0.8}),
    ("потолок 1.5 + top-p 0.9", {"cap_mult": 1.5, "amount_top_p": 0.9}),
    ("потолок 1.0 + top-p 0.8", {"cap_mult": 1.0, "amount_top_p": 0.8}),
    ("потолок 2 + t 0.7 + top-p 0.9", {"cap_mult": 2.0, "amount_temperature": 0.7, "amount_top_p": 0.9}),
    ("всё t 0.9 + потолок 1.5", {"cap_mult": 1.5, "temperature": 0.9}),
]
BLEND_W30 = (1.0, 0.75, 0.5, 0.25, 0.0)


def correction(rows: list[dict]) -> tuple[float, float]:
    """k_in, k_out: факт / сгенерированное за горизонт (по сумме точек старта)."""
    s = lambda k: sum(r[k] for r in rows)
    return s("act_in") / max(s("gen_in"), 1.0), s("act_out") / max(s("gen_out"), 1.0)


def blend(rows: list[dict], w30: float, horizon: int, k: tuple[float, float] = (1.0, 1.0)) -> list[dict]:
    w = 1.0 - (1.0 - w30) * np.arange(horizon) / max(horizon - 1, 1)
    out = []
    for r in rows:
        trx = r["start"] + k[0] * r["trx_cin"] - k[1] * r["trx_cout"]
        out.append({**r, "mix_bal": w * trx + (1 - w) * r["naive_bal"]})
    return out


def score(m: dict) -> float:
    """Чем меньше, тем лучше: средняя WAPE по горизонтам + ошибка вероятности разрыва
    + штраф за коридор p10–p90 далеко от 80%."""
    return float(np.mean([m["wape_7"], m["wape_14"], m["wape_30"]]) + m["gap_brier"] + 0.5 * abs(m["coverage"] - 0.8))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", type=Path, default=Path("runs/finetune-v2/final.pt"))
    p.add_argument("--shard", type=Path, default=ML_DIR / "data" / "trx" / "case")
    p.add_argument("--flows", type=Path, default=ML_DIR / "data" / "flows.csv")
    p.add_argument("--out", type=Path, default=Path("runs/gen-tune"))
    p.add_argument("--min-origin", default="2026-07-01")
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--origins", type=int, default=2)
    p.add_argument("--paths", type=int, default=40, help="путей при подборе (на аудите — --final-paths)")
    p.add_argument("--final-paths", type=int, default=100)
    p.add_argument("--max-companies", type=int, default=0, help="для пробного запуска")
    p.add_argument("--skip-audit", action="store_true")
    p.add_argument("--device", default="auto")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    device = pick_device(a.device)
    model, vocab, _ = load_model(a.model, map_location="cpu")
    model.to(device)
    shard = Shard(a.shard)
    flows = load_flows(a.flows)
    min_origin = int(np.datetime64(a.min_origin, "D").astype(np.int64))
    dev = select_companies(shard, flows, {"development"}, (80, 100), a.max_companies)
    print(f"подбор: {len(dev)} компаний разработки (корзины 80–100), точки старта с {a.min_origin}, "
          f"{len(CONFIGS)} настроек × {a.paths} путей", flush=True)

    table = []
    for name, kw in CONFIGS:
        t0 = time.time()
        rows = backtest(model, vocab, shard, flows, dev, min_origin, a.horizon, 30, a.origins, a.paths, device, kw,
                        verbose=False)
        if not rows:
            raise SystemExit("нет точек старта у компаний разработки после --min-origin")
        b = bias(rows)
        kc = correction(rows)
        for corr, k in (("нет", (1.0, 1.0)), ("да", kc)):
            for w30 in BLEND_W30:
                m = summarize(blend(rows, w30, a.horizon, k), "mix", 0.3)
                table.append({"config": name, "corr": corr, "k_in": k[0], "k_out": k[1], "w30": w30,
                              **{key: v for key, v in m.items() if key != "model"}, **b, "score": score(m),
                              "kw": json.dumps(kw)})
        pure = [t for t in table if t["config"] == name and t["w30"] == 1.0 and t["corr"] == "нет"][0]
        print(f"{name:32s} WAPE {pure['wape_7']:.3f} / {pure['wape_14']:.3f} / {pure['wape_30']:.3f}, "
              f"коридор {pure['coverage']:.2f}, Brier {pure['gap_brier']:.3f} | смещение: приходы ×{b['in_ratio']:.2f}, "
              f"расходы ×{b['out_ratio']:.2f}, операций ×{b['ops_ratio']:.2f} | {(time.time() - t0) / 60:.1f} мин",
              flush=True)
        pd.DataFrame(table).drop(columns="kw").to_csv(a.out / "report.csv", index=False)

    df = pd.DataFrame(table)
    naive = summarize(rows, "naive", 0.3)  # пути naive не зависят от настроек генерации
    best = df.loc[df["score"].idxmin()]
    pd.set_option("display.width", 220)
    cols = [c for c in ["config", "corr", "w30", "wape_7", "wape_14", "wape_30", "coverage", "gap_brier", "gap_auc",
                        "score"] if c in df.columns]
    print("\nлучшие 8 по сумме ошибок:")
    print(df.sort_values("score")[cols].head(8).round(3).to_string(index=False))
    print(f"naive на тех же точках: WAPE {naive['wape_7']:.3f} / {naive['wape_14']:.3f} / {naive['wape_30']:.3f}, "
          f"коридор {naive['coverage']:.2f}, Brier {naive['gap_brier']:.3f}")
    info = {"config": best["config"], "generate": json.loads(best["kw"]), "blend_w30": float(best["w30"]),
            "k_in": float(best["k_in"]), "k_out": float(best["k_out"]),
            "dev": {k: float(best[k]) for k in ("wape_7", "wape_14", "wape_30", "coverage", "gap_brier")}}
    (a.out / "best.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(f"\nлучшее: {info['config']}, поправка приходов ×{info['k_in']:.2f}, расходов ×{info['k_out']:.2f}, "
          f"вес TrxGPT на 30-й день {info['blend_w30']} → {a.out / 'best.json'}")

    if a.skip_audit:
        return
    print("\n=== аудит (30 новых компаний), один раз: исходная генерация против лучшей ===", flush=True)
    aud = select_companies(shard, flows, {"audit"}, None, a.max_companies)
    out = []
    for label, kw, w30, k in (("исходная", {}, 1.0, (1.0, 1.0)),
                              ("лучшая", info["generate"], info["blend_w30"], (info["k_in"], info["k_out"]))):
        rows = backtest(model, vocab, shard, flows, aud, min_origin, a.horizon, 30, 6, a.final_paths, device, kw,
                        verbose=False)
        out.append({**summarize(blend(rows, w30, a.horizon, k), "mix", 0.3), **bias(rows), "model": f"trx {label}"})
        print(f"  {label}: готово", flush=True)
    out.append({**summarize(rows, "naive", 0.3), "model": "naive"})
    res = pd.DataFrame(out)
    res.to_csv(a.out / "audit.csv", index=False)
    show = [c for c in ["model", "runs", "wape_7", "wape_14", "wape_30", "coverage", "gap_brier", "gap_auc",
                        "gap_precision", "gap_recall"] if c in res.columns]
    print(res[show].round(3).to_string(index=False))
    print(f"\nотчёты: {a.out / 'report.csv'}, {a.out / 'audit.csv'}")


if __name__ == "__main__":
    torch.set_grad_enabled(False)
    main()

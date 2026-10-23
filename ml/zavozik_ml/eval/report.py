"""Отчёт о качестве прогноза для презентации: таблица метрик + графики.

    python -m zavozik_ml.eval.report        # после eval.backtest

Пишет ml/reports/quality.md и PNG рядом.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from zavozik_ml.data import DEFAULT_FLOWS  # noqa: E402

REPORTS = Path(__file__).resolve().parents[2] / "reports"

# Палитра: категориальные слоты в фиксированном порядке, цвет закреплён за
# моделью; у линий прямые подписи. Текст и сетка — нейтральные чернила.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LABELS = {
    "seasonal_naive": "Seasonal naive",
    "ets": "ETS (Holt-Winters)",
    "gbm_global": "LightGBM глобальная",
    "ensemble": "Ансамбль LightGBM + naive",
}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def wape_by_horizon(df: pd.DataFrame, out: Path, column: str = "actual") -> None:
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=160, facecolor=SURFACE)
    _style(ax)
    ends = []
    for color, m in zip(SERIES, LABELS):
        if m not in set(df.model):
            continue
        g = df[df.model == m].groupby("h").apply(lambda x: (x[column] - x.p50).abs().sum() / x[column].abs().sum())
        ax.plot(g.index, g.values * 100, color=color, linewidth=2)
        ends.append([g.values[-1] * 100, LABELS[m], g.index[-1]])
    # Прямые подписи у концов линий, разнесённые, чтобы не наезжали.
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 3.5)
    for y, label, x in ends:
        ax.annotate(label, (x, y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.set_xlabel("Горизонт, дней", color=INK_2, fontsize=9)
    ax.set_ylabel("WAPE остатка, %", color=INK_2, fontsize=9)
    ax.set_xlim(1, 30)
    ax.set_ylim(bottom=0)
    ax.set_title("Ошибка прогноза остатка по горизонту (меньше — лучше)", loc="left", color=INK, fontsize=11)
    fig.subplots_adjust(right=0.74)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def fan_chart(df: pd.DataFrame, flows: pd.DataFrame, model: str, company: str, as_of, out: Path) -> None:
    g = df[(df.model == model) & (df.company_id == company) & (df.as_of == as_of)].sort_values("h")
    hist = flows[(flows.company_id == company) & (flows.date <= pd.Timestamp(as_of))].tail(60)
    dates = pd.Timestamp(as_of) + pd.to_timedelta(g.h, unit="D")
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=160, facecolor=SURFACE)
    _style(ax)
    m = 1e6
    ax.plot(hist.date, hist.balance / m, color=INK_2, linewidth=2, label="Факт до прогноза")
    ax.fill_between(dates, g.p10 / m, g.p90 / m, color=SERIES[0], alpha=0.18, linewidth=0, label="Коридор p10–p90")
    ax.plot(dates, g.p50 / m, color=SERIES[0], linewidth=2, label="Прогноз (медиана)")
    ax.plot(dates, g.actual / m, color=INK_2, linewidth=1.5, linestyle=(0, (1, 2)), label="Факт на счёте")
    ax.plot(dates, g.adjusted / m, color=INK, linewidth=1.5, linestyle=(0, (4, 2)), label="Факт без денег владельца")
    ax.axhline(0, color=SERIES[1], linewidth=1)
    ax.set_ylabel("Остаток, млн ₽", color=INK_2, fontsize=9)
    ax.set_title(f"Прогноз остатка на 30 дней: компания {company}, от {as_of}", loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower left")
    fig.autofmt_xdate()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)


def pick_demo(df: pd.DataFrame, model: str):
    """Точка старта с реальным разрывом, который модель увидела заранее."""
    g = df[(df.model == model) & (df.h == 1)]
    hit = g[g.gap_true & (g.gap_prob >= 0.3) & (g.gap_day >= 7)].sort_values("gap_prob", ascending=False)
    row = (hit if len(hit) else g).iloc[0]
    return row.company_id, row.as_of


def to_markdown(summary: pd.DataFrame) -> str:
    cols = {
        "model": "Модель", "companies": "Компании", "runs": "Прогонов",
        "wape_7": "WAPE 7д", "wape_14": "WAPE 14д", "wape_30": "WAPE 30д", "coverage": "Покрытие p10–p90",
        "biz_wape_30": "WAPE 30д (бизнес)", "rel_mae_gmean": "Ошибка к naive",
        "win_rate": "Лучше naive", "gap_auc": "Разрывы: AUC", "gap_precision": "Разрывы: точность",
        "gap_recall": "Разрывы: полнота", "gap_lead_days": "За сколько дней",
    }
    t = summary[list(cols)].copy()
    t["model"] = t.model.map(lambda m: LABELS.get(m, m))
    t["companies"] = t.companies.map({"all": "все", "seen": "из обучения", "unseen": "новые"})
    for c in ("wape_7", "wape_14", "wape_30", "coverage", "biz_wape_30", "win_rate", "gap_precision", "gap_recall"):
        t[c] = (t[c] * 100).round(1).astype(str) + "%"
    t.loc[summary.model == "seasonal_naive", "win_rate"] = "—"  # бейзлайн сам с собой не сравниваем
    t["gap_lead_days"] = t.gap_lead_days.round(1)
    t["rel_mae_gmean"] = t.rel_mae_gmean.round(2)
    t["gap_auc"] = t.gap_auc.round(3)
    t = t.rename(columns=cols)
    header = "| " + " | ".join(t.columns) + " |\n|" + "---|" * len(t.columns) + "\n"
    return header + "\n".join("| " + " | ".join(map(str, r)) + " |" for r in t.itertuples(index=False))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", type=Path, default=DEFAULT_FLOWS.parent / "backtest_py.parquet")
    p.add_argument("--best", default="gbm_global")
    args = p.parse_args()

    df = pd.read_parquet(args.results)
    summary = pd.read_csv(args.results.with_suffix(".summary.csv"))
    flows = pd.read_csv(DEFAULT_FLOWS, usecols=["company_id", "date", "balance"], parse_dates=["date"])
    REPORTS.mkdir(parents=True, exist_ok=True)

    wape_by_horizon(df, REPORTS / "wape_by_horizon.png")
    company, as_of = pick_demo(df, args.best)
    fan_chart(df, flows, args.best, company, as_of, REPORTS / "fan_chart.png")

    md = f"""# Качество прогноза остатка

Бэктест на датасете кейса: {df.company_id.nunique()} компаний с подходящей историей, {df.groupby(['model']).size().iloc[0] // 30} прогонов на модель,
горизонт 30 дней, 6 точек старта на компанию с шагом 30 дней. Глобальная модель
переобучается раз в месяц только на данных до точки старта; 20% компаний она не
видит вообще («новые»).

- **WAPE** — суммарная абсолютная ошибка медианы прогноза остатка / сумма |остатка|.
- **WAPE (бизнес)** — то же против остатка без переводов владельца (займы
  учредителя, переводы своих средств): их не предсказать по потокам бизнеса.
- **Покрытие p10–p90** — доля дней, когда факт внутри коридора (цель — 80%).
- **Ошибка к naive** — средняя (геометрическая) по прогонам ошибка модели,
  делённая на ошибку seasonal naive на том же прогоне: не зависит от размера
  компании, < 1 — лучше бейзлайна. **Лучше naive** — доля таких прогонов.
- **Разрывы** — остаток без докачки владельцем уходит ниже нуля на горизонте;
  прогноз разрыва — вероятность ≥ 30%. «За сколько дней» — как рано увидели.

{to_markdown(summary)}

![WAPE по горизонту](wape_by_horizon.png)

![Пример прогноза](fan_chart.png)
"""
    (REPORTS / "quality.md").write_text(md)
    print(f"report: {REPORTS / 'quality.md'}")


if __name__ == "__main__":
    main()

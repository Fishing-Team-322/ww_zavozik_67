"""Отчёт о качестве прогноза для презентации: таблица метрик + графики.

    python -m zavozik_ml.eval.report        # после eval.backtest

Пишет ml/reports/quality.md и PNG рядом.
"""

from __future__ import annotations

import argparse
import json
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
    """Median-error example, deterministic; no selection for an impressive hit."""
    g = df[df.model == model].groupby(["company_id", "as_of"]).agg(mae=("mae_run", "first")).reset_index()
    if g.empty:
        raise ValueError(f"no results for model {model}")
    row = g.sort_values(["mae", "company_id", "as_of"]).iloc[len(g)//2]
    return row.company_id, row.as_of


def by_industry(df: pd.DataFrame) -> str:
    g = df[df.h == 30].copy()
    g["err"] = (g.actual - g.p50).abs()
    t = g.groupby(["industry", "model"]).apply(lambda x: x.err.sum() / x.actual.abs().sum()).unstack()
    t = t[[m for m in LABELS if m in t]].sort_values(t.columns[-1])
    lines = ["| Отрасль | " + " | ".join(LABELS[m] for m in t.columns) + " |", "|---|" + "---|" * len(t.columns)]
    for ind, row in t.iterrows():
        lines.append(f"| {ind} | " + " | ".join(f"{v * 100:.0f}%" for v in row) + " |")
    return "\n".join(lines)


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


def metric_table(frame: pd.DataFrame, columns: dict[str, str]) -> str:
    columns = {k: v for k, v in columns.items() if k in frame}
    rows = []
    for _, row in frame.iterrows():
        cells = []
        for key in columns:
            v = row[key]
            if isinstance(v, (float, np.floating)):
                cells.append("—" if not np.isfinite(v) else f"{v:.3f}")
            else:
                cells.append(str(v).replace("|", "/"))
        rows.append("| " + " | ".join(cells) + " |")
    return "| " + " | ".join(columns.values()) + " |\n|" + "---|"*len(columns) + "\n" + "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", type=Path, default=DEFAULT_FLOWS.parent / "backtest_py.parquet")
    p.add_argument("--flows", type=Path, default=DEFAULT_FLOWS)
    p.add_argument("--out", type=Path, default=REPORTS / "quality.md")
    p.add_argument("--best", default="ensemble", help="model for representative example; does not select a winner")
    args = p.parse_args()
    df = pd.read_parquet(args.results)
    summary = pd.read_csv(args.results.with_suffix(".summary.csv"))
    meta = json.loads(args.results.with_suffix(".metadata.json").read_text())
    if "scenario" not in summary:
        summary["scenario"] = "standard"
    if "scenario" in df:
        df = df[df.scenario == "standard"]
    s = summary[(summary.companies == "all") & (summary.scenario == "standard")]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    figures = args.out.parent
    prefix = args.out.stem
    dates = sorted(str(d) for d in df.as_of.unique())
    lines = ["# Проверка прогноза денежных потоков", "",
        f"Протокол: **{meta['protocol']}**; CV по компаниям: {meta['cv']}; "
        f"{df.company_id.nunique()} компаний; {df[['company_id', 'as_of']].drop_duplicates().shape[0]} точек старта на модель. "
        f"Даты: {', '.join(dates)}. Горизонт {meta['horizon']} дней, {meta['paths']} путей, seed {meta['seed']}.", "",
        "Обучение использует только прошлое относительно даты прогноза. "
        "В development с CV каждая оцениваемая компания исключена из обучения своего fold; "
        "в audit фиксированные аудит-компании исключены из всех обучений. "
        "Обычный development без CV оценивает знакомые компании и не заменяет проверку обобщения.", "",
        "Все исходные компании ранее исследовались при разработке. Это внутренняя проверка на синтетических выписках, "
        "а не независимый внешний тест и не гарантия качества на настоящем бизнесе.", "",
        "## Остаток и неопределённость", "",
        "Модель прогнозирует бизнес-потоки без own_transfer/owner_loan, включая регулярные зарплату, налоги и аренду. "
        "Основная цель — начальный остаток плюс эти потоки. Account — наблюдаемый остаток счёта, "
        "который дополнительно меняют переводы владельца. Эти цели нельзя смешивать.", "",
        "WAPE 7/14/30 — ошибка в конкретный день горизонта. Path WAPE — ошибка по всем дням. "
        "Числа являются долями (0.25 = 25%). Покрытие p10–p90 должно быть около 0.80; "
        "слишком широкий интервал тоже нежелателен, поэтому рядом pinball loss. "
        "Relative MAE и win rate сравнивают account MAE с naive на каждой той же точке старта.", "",
        metric_table(s, {"model":"Модель", "runs":"N", "biz_wape_7":"Business WAPE 7", "biz_wape_14":"14", "biz_wape_30":"30",
                        "business_path_wape":"Business path WAPE", "biz_coverage":"Покрытие", "biz_pinball":"Pinball",
                        "wape_30":"Account WAPE 30", "rel_mae_gmean":"Relative MAE", "win_rate":"Win rate"}), "",
        "## Кассовые разрывы", "",
        f"Предупреждение совпадает с Go risk.FindGaps: первый день, где P(остаток < 0) ≥ {meta['gap_threshold']}. "
        "Вероятность события на всём горизонте считается отдельно: доля путей хотя бы с одним отрицательным остатком. "
        "Brier/ECE ниже относятся к вероятности события на горизонте. Date MAE — ошибка даты среди верно найденных событий, "
        "а не заблаговременность. Shortfall MAE — ошибка медианной нехватки по всем фактическим бизнес-разрывам, в рублях.", "",
        metric_table(s, {"model":"Модель", "gap_events":"Событий", "gap_alerts":"Сигналов", "gap_false_alerts":"Ложных",
                        "gap_precision":"Precision", "gap_recall":"Recall", "gap_brier":"Brier", "gap_ece":"ECE",
                        "gap_date_mae_days":"Date MAE, дни", "gap_shortfall_mae":"Shortfall MAE, ₽"}), "",
        "Account-показатели ниже диагностические: бизнес-сценарий не моделирует будущую финансовую помощь владельца.", "",
        metric_table(s, {"model":"Модель", "account_gap_events":"Account событий", "account_gap_precision":"Precision",
                        "account_gap_recall":"Recall", "account_gap_brier":"Brier", "opening_negative_runs":"Уже ниже нуля",
                        "new_gap_events":"Новых business событий", "new_gap_recall":"Recall новых",
                        "daily_gap_brier":"Daily Brier", "daily_gap_ece":"Daily ECE"})]
    for suffix, title, cols in [
        ("segments", "Сегменты доступной истории", {"segment":"Сегмент", "model":"Модель", "runs":"N", "business_path_wape":"Path WAPE",
            "biz_coverage":"Покрытие", "gap_precision":"Precision", "gap_recall":"Recall", "low_confidence_share":"Low confidence"}),
        ("calibration", "Калибровка вероятности события на горизонте", {"model":"Модель", "lower":"От", "upper":"До", "n":"N",
            "mean_prediction":"Прогноз", "business_frequency":"Business факт", "account_frequency":"Account факт"})]:
        path = args.results.with_suffix(f".{suffix}.csv")
        if path.exists():
            t = pd.read_csv(path)
            lines += ["", f"## {title}", "", metric_table(t, cols)]
    stress = summary[(summary.companies == "all") & (summary.scenario != "standard")]
    if len(stress):
        lines += ["", "## Контролируемое ухудшение входа", "",
            "Будущий факт неизменен. short — только последние N дней; gap_14 — скрытые 14 дней перед последней неделей; "
            "missing_30pct — детерминированно скрытые 30% дней. Это стресс-проверка, а не новый независимый датасет.", "",
            metric_table(stress, {"scenario":"Сценарий", "model":"Модель", "runs":"N", "business_path_wape":"Path WAPE",
                                 "biz_coverage":"Покрытие", "gap_precision":"Precision", "gap_recall":"Recall",
                                 "low_confidence_share":"Low confidence"})]
    if len(df):
        wape_by_horizon(df, figures / f"{prefix}_wape.png", column="adjusted")
        lines += ["", f"![Business WAPE по горизонту]({prefix}_wape.png)"]
        if args.flows.exists():
            flows = pd.read_csv(args.flows, usecols=["company_id", "date", "balance"], parse_dates=["date"])
            company, as_of = pick_demo(df, args.best)
            fan_chart(df, flows, args.best, company, as_of, figures / f"{prefix}_example.png")
            lines += ["", "Пример выбран по медианной ошибке модели, а не по удачно предсказанному разрыву.", "",
                      f"![Типичный пример]({prefix}_example.png)"]
    lines += ["", "## Воспроизводимость", "", f"Вход: `{meta['flows_sha256']}`.",
              f"Код на старте: `{meta.get('source_sha256_at_start', 'не записан в раннем прогоне')}`.",
              f"Код менялся во время прогона: `{meta.get('source_changed_during_run', 'unknown')}`.",
              f"Полные результаты и настройки: `{args.results.name}`, `{args.results.with_suffix('.metadata.json').name}`."]
    args.out.write_text("\n".join(lines) + "\n")
    print(f"report: {args.out}")


if __name__ == "__main__":
    main()

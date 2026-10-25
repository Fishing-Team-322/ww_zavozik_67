"""Событийный hybrid (event_forecasters.hybrid) как обычный Forecaster.

Модель разыгрывает отдельные операции, а не дневные суммы:
  * регулярные потоки (контрагент + направление + категория с устойчивым ритмом: день месяца,
    первый/последний рабочий день, налоговые даты, еженедельно) ставятся на свои даты;
  * всё, что регулярным потоком не объясняется, — бутстрап целых недель из истории компании.

На входе нужны операции: History.transactions (Go их присылает). Если операций нет или на какой-то
день они не сходятся с дневным потоком, день берётся одной операцией на сумму inflow / outflow —
итог всегда совпадает с дневными потоками, но регулярные платежи такого дня ищутся только по сумме.

Модель локальная: обучение на других компаниях (априорные частоты и суммы потоков) на протоколе
trx/evaluate.py почти ничего не даёт (WAPE 30 дн. 0.384 без обучения против 0.376 с ним),
поэтому артефакта нет и модель готова сразу.

Метрики этой обёртки на протоколе trx/evaluate.py (30 audit-компаний, 86 точек, 9 разрывов):
WAPE 7/14/30 дн. 0.165 / 0.272 / 0.384 против 0.172 / 0.342 / 0.513 у seasonal naive (тот же прогон),
Brier 0.075 против 0.097, покрытие p10–p90 0.83; structural_m6 — 0.166 / 0.311 / 0.412, Brier 0.091.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import INTERNAL_CATEGORIES, Forecaster, History, InsufficientHistoryError, Paths, register
from .naive import MIN_CONFIDENT_DAYS

# Расхождение операций с дневным потоком, после которого день заменяется одной операцией на всю сумму.
RECONCILE_TOLERANCE = 1.0


def event_history(history: History):
    """History → EventHistory: операции бизнеса, сверенные с дневными inflow / outflow."""
    from zavozik_ml.event_forecasters.core import EventHistory

    dates = np.asarray(history.dates, dtype="datetime64[D]")
    n = len(dates)
    rows = [t for t in history.transactions if t.get("category") not in INTERNAL_CATEGORIES]
    tx = pd.DataFrame(rows, columns=["date", "amount", "direction", "category", "counterparty_id"])
    tx = tx[tx["direction"].isin(("in", "out"))]
    day = (pd.to_datetime(tx["date"]).to_numpy(dtype="datetime64[D]") - dates[0]).astype(int) if len(tx) else []
    tx = tx.assign(day=day, direction=(tx["direction"] == "out").astype(int), amount=tx["amount"].astype(float).abs())
    tx = tx[(tx["day"] >= 0) & (tx["day"] < n)]
    flows = np.stack([history.inflow, history.outflow], axis=1).astype(float)
    summed = np.zeros((n, 2))
    np.add.at(summed, (tx["day"].to_numpy(int), tx["direction"].to_numpy(int)), tx["amount"].to_numpy())
    agree = np.abs(summed - flows) <= np.maximum(RECONCILE_TOLERANCE, 1e-6 * flows)
    keep = agree[tx["day"].to_numpy(int), tx["direction"].to_numpy(int)]
    events = [pd.DataFrame({"day": tx["day"][keep], "direction": tx["direction"][keep], "amount": tx["amount"][keep],
                            "category": tx["category"][keep].fillna("").replace("", "unknown").astype(str),
                            "counterparty": tx["counterparty_id"][keep].fillna("").astype(str)})]
    missing = np.asarray(history.missing, dtype=bool)
    d, k = np.nonzero(~agree & (flows > 0) & ~missing[:, None])
    events.append(pd.DataFrame({"day": d, "direction": k, "amount": flows[d, k], "category": "unknown",
                                "counterparty": ""}))
    ev = pd.concat(events, ignore_index=True)
    ev = ev[~missing[ev["day"].to_numpy(int)]]
    ev.insert(0, "date", pd.to_datetime(dates[ev["day"].to_numpy(int)]))
    known = history.missing_known_on
    detected = np.where(missing, dates, np.datetime64("NaT", "D")) if known is None else \
        np.where(missing & np.isnat(known), dates, known).astype("datetime64[D]")
    return EventHistory("", history.industry, dates, missing, detected,
                        ev.drop(columns="day").reset_index(drop=True))


@register
class EventHybrid(Forecaster):
    name = "event_hybrid"
    description = "Регулярные потоки по контрагентам + бутстрап недель, на уровне отдельных операций"

    def __init__(self) -> None:
        self._model = None

    def _get_model(self):
        if self._model is None:
            from zavozik_ml.event_forecasters.hybrid import Model

            self._model = Model()
        return self._model

    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths:
        if history.valid_days == 0:
            raise InsufficientHistoryError("history contains no observed days")
        sampled = self._get_model().sample(event_history(history), horizon, n_paths, rng)
        amounts, _ = sampled.daily()
        return Paths(amounts[:, :, 0], amounts[:, :, 1], low_confidence=history.valid_days < MIN_CONFIDENT_DAYS)

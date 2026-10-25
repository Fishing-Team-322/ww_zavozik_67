"""Структурная модель M6 (cashradar): регулярные платежи + счета + бутстрэп, уровень — LightGBM.

    pip install ml/vendor/cashradar-*.whl      # numpy, pandas, pyyaml; lightgbm уже есть

Что делает модель:
  * находит регулярные обязательства (зарплата, налоги, аренда, кредиты…) и ставит их на даты
    с переносом на рабочий день;
  * если в History есть транзакции с назначениями — восстанавливает открытые счета клиентов
    и поставщиков и разыгрывает срок их оплаты по истории контрагента (марковская модель по возрасту счёта);
  * остальной поток — блочный бутстрап последних 12 недель с поправкой на сезонность;
  * среднее сдвигается к прогнозу глобального LightGBM (вес M5 = 0.6, после 30 дней — чистая M5).
Без транзакций модель работает по суммам категорий (режим lite), без категорий — по дневным потокам.

Метрики на протоколе trx/evaluate.py (30 audit-компаний, 86 точек, 9 разрывов):
WAPE 30 дн. 0.412 против 0.478 у seasonal naive и 1.315 у trx; Brier 0.091 против 0.096 / 0.295
(только выписка: реестр счетов на дату прогноза знает лишь уже оплаченные счета).
"""

from __future__ import annotations

import numpy as np

from .base import Forecaster, History, InsufficientHistoryError, NotTrainedError, Paths, register


@register
class StructuralM6(Forecaster):
    name = "structural_m6"
    description = "Регулярные платежи + счета + бутстрап (Монте-Карло), уровень по LightGBM — cashradar M6"

    def __init__(self) -> None:
        self._engine = None  # ленивая загрузка: регистрация не должна требовать cashradar

    @property
    def ready(self) -> bool:
        try:
            import cashradar.embed  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_engine(self):
        if self._engine is None:
            try:
                from cashradar.embed import M5Engine
            except ImportError as e:
                raise NotTrainedError("cashradar is not installed: pip install ml/vendor/cashradar-*.whl") from e
            self._engine = M5Engine()
        return self._engine

    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths:
        if history.valid_days == 0:
            raise InsufficientHistoryError("history contains no observed days")
        engine = self._get_engine()
        res = engine.forecast(
            history.dates, history.inflow, history.outflow, history.missing,
            horizon=horizon, n_paths=n_paths, seed=int(rng.integers(0, 2**31 - 1)),
            categories=history.categories or None,
            transactions=[dict(t) for t in history.transactions] or None,
            industry=history.industry,
        )
        return Paths(res.inflow, res.outflow, low_confidence=res.low_confidence)

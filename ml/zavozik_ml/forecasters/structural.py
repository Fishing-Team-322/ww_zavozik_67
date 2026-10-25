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
WAPE 30 дн. 0.393 против 0.478 у seasonal naive и 1.315 у trx; Brier 0.085 против 0.096 / 0.295.
"""

from __future__ import annotations

import os
import json
import logging
import time
import uuid
import numpy as np

from .base import Forecaster, History, InsufficientHistoryError, NotTrainedError, Paths, register


_checkpoint_log = logging.getLogger("zavozik_ml.checkpoint")


def _checkpoint_event(trace: str, phase: str, **fields) -> None:
    # Observability must not alter a successful forecast or replace its error.
    # Call sites pass only wrapper counts, shapes, timing and exception type.
    try:
        _checkpoint_log.info("%s", json.dumps({
            "event": "m6_wrapper_observation", "trace": trace,
            "phase": phase, **fields,
        }, sort_keys=True))
    except Exception:
        pass


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
        if os.getenv("ML_REQUIRE_M6_GBM")=="true":
            try:
                return self._get_engine().gbm is not None
            except NotTrainedError:
                return False
        return True

    def _get_engine(self):
        if self._engine is None:
            try:
                from cashradar.embed import M5Engine
            except ImportError as e:
                raise NotTrainedError("cashradar is not installed: pip install ml/vendor/cashradar-*.whl") from e
            self._engine = M5Engine()
        if os.getenv("ML_REQUIRE_M6_GBM")=="true" and self._engine.gbm is None:
            raise NotTrainedError("M6 LightGBM artifact is unavailable")
        return self._engine

    def forecast(self, history: History, horizon: int, n_paths: int, rng: np.random.Generator) -> Paths:
        trace = uuid.uuid4().hex
        started = time.monotonic()
        phase = "history_validation"
        try:
            if history.valid_days == 0:
                raise InsufficientHistoryError("history contains no observed days")
            _checkpoint_event(
                trace, "history_accepted", history_days=len(history.dates),
                valid_days=history.valid_days, transaction_count=len(history.transactions),
                category_count=len(history.categories), horizon=horizon, n_paths=n_paths,
            )
            phase = "engine_loading"
            engine = self._get_engine()
            _checkpoint_event(trace, "engine_ready")
            phase = "engine_call"
            _checkpoint_event(trace, "engine_call_started")
            res = engine.forecast(
                history.dates, history.inflow, history.outflow, history.missing,
                horizon=horizon, n_paths=n_paths, seed=int(rng.integers(0, 2**31 - 1)),
                categories=history.categories or None,
                transactions=[dict(t) for t in history.transactions] or None,
                industry=history.industry,
            )
            result = Paths(res.inflow, res.outflow, low_confidence=res.low_confidence, warnings=tuple(res.warnings))
            _checkpoint_event(
                trace, "engine_call_returned", inflow_shape=list(res.inflow.shape),
                outflow_shape=list(res.outflow.shape), low_confidence=bool(res.low_confidence),
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            return result
        except Exception as exc:
            _checkpoint_event(
                trace, "error", failed_phase=phase, exception_type=type(exc).__name__,
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            raise

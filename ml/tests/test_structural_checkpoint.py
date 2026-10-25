"""Wrapper observations are factual and never disclose financial input or error text."""
from datetime import date, timedelta
import json
import logging
from types import SimpleNamespace

import numpy as np
import pytest

from zavozik_ml.forecasters.base import History, InsufficientHistoryError
from zavozik_ml.forecasters import structural

LOG = "zavozik_ml.checkpoint"
SECRETS = ("PRIVATE_PURPOSE", "PRIVATE_COUNTERPARTY", "PRIVATE_COMPANY", "PRIVATE_INDUSTRY", "7654321.25", "2031-02-03")


def history():
    return History(
        dates=[date(2031, 2, 3) + timedelta(days=i) for i in range(3)],
        inflow=np.array([7654321.25, 2., 3.]), outflow=np.array([1., 1., 1.]),
        missing=np.zeros(3, dtype=bool), industry="PRIVATE_INDUSTRY",
        categories={"salary": np.array([-1., -1., -1.])},
        transactions=({"id": "PRIVATE_COMPANY", "date": "2031-02-03", "amount": 7654321.25,
                       "counterparty_id": "PRIVATE_COUNTERPARTY", "purpose": "PRIVATE_PURPOSE"},),
    )


def events(caplog):
    rows = [json.loads(r.getMessage()) for r in caplog.records if r.name == LOG]
    assert rows
    assert len({r["trace"] for r in rows}) == 1
    for secret in SECRETS:
        assert secret not in caplog.text
    for row in rows:
        assert row["event"] == "m6_wrapper_observation"
        assert "company_id" not in row and "seed" not in row
    return rows


class FakeEngine:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def forecast(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        r = np.random.default_rng(kwargs["seed"])
        shape = (kwargs["n_paths"], kwargs["horizon"])
        self.result = SimpleNamespace(inflow=r.uniform(size=shape), outflow=r.uniform(size=shape),
                                      low_confidence=True, warnings=["fixed_warning"])
        return self.result


def test_success_events_preserve_arguments_paths_and_rng(caplog, monkeypatch):
    h = history()
    engine = FakeEngine()
    model = structural.StructuralM6()
    monkeypatch.setattr(model, "_get_engine", lambda: engine)
    rng = np.random.default_rng(71)
    expected_rng = np.random.default_rng(71)
    expected_seed = int(expected_rng.integers(0, 2**31 - 1))
    with caplog.at_level(logging.INFO, logger=LOG):
        actual = model.forecast(h, 4, 2, rng)
    rows = events(caplog)
    assert [r["phase"] for r in rows] == ["history_accepted", "engine_ready", "engine_call_started", "engine_call_returned"]
    assert rows[0]["history_days"] == 3 and rows[0]["valid_days"] == 3
    assert rows[0]["transaction_count"] == rows[0]["category_count"] == 1
    assert rows[-1]["inflow_shape"] == rows[-1]["outflow_shape"] == [2, 4]
    args, kw = engine.calls[0]
    assert all(actual_arg is original_arg for actual_arg, original_arg in zip(args, (h.dates, h.inflow, h.outflow, h.missing)))
    assert kw["categories"] is h.categories
    assert kw["transactions"] == list(h.transactions) and kw["transactions"][0] is not h.transactions[0]
    assert kw["industry"] == h.industry and kw["seed"] == expected_seed
    expected_paths_rng = np.random.default_rng(expected_seed)
    np.testing.assert_array_equal(actual.inflow, expected_paths_rng.uniform(size=(2, 4)))
    np.testing.assert_array_equal(actual.outflow, expected_paths_rng.uniform(size=(2, 4)))
    assert actual.inflow is engine.result.inflow and actual.outflow is engine.result.outflow
    assert actual.low_confidence is True and actual.warnings == ("fixed_warning",)
    assert rng.bit_generator.state == expected_rng.bit_generator.state


@pytest.mark.parametrize("failed_phase", ["history_validation", "engine_loading", "engine_call"])
def test_error_events_preserve_exception_and_rng(caplog, monkeypatch, failed_phase):
    h = history()
    error = RuntimeError("PRIVATE_PURPOSE PRIVATE_COUNTERPARTY PRIVATE_COMPANY 7654321.25 2031-02-03")
    model = structural.StructuralM6()
    engine = FakeEngine(error=error)
    if failed_phase == "history_validation":
        h = History(h.dates, h.inflow, h.outflow, np.ones(3, dtype=bool))
        error_type = InsufficientHistoryError
    else:
        error_type = RuntimeError
    def get_engine():
        if failed_phase == "engine_loading":
            raise error
        return engine
    monkeypatch.setattr(model, "_get_engine", get_engine)
    rng = np.random.default_rng(71)
    expected_rng = np.random.default_rng(71)
    if failed_phase == "engine_call":
        expected_rng.integers(0, 2**31 - 1)
    with caplog.at_level(logging.INFO, logger=LOG), pytest.raises(error_type) as caught:
        model.forecast(h, 4, 2, rng)
    if failed_phase != "history_validation":
        assert caught.value is error
    rows = events(caplog)
    assert rows[-1]["phase"] == "error" and rows[-1]["failed_phase"] == failed_phase
    assert rows[-1]["exception_type"] == error_type.__name__
    assert not any(r["phase"] == "engine_call_returned" for r in rows)
    assert rng.bit_generator.state == expected_rng.bit_generator.state


def test_log_sink_failure_does_not_change_forecast_or_rng(monkeypatch):
    h = history()
    model = structural.StructuralM6()
    engine = FakeEngine()
    monkeypatch.setattr(model, "_get_engine", lambda: engine)
    def broken_log(*args, **kwargs):
        raise OSError("PRIVATE_PURPOSE")
    monkeypatch.setattr(structural._checkpoint_log, "info", broken_log)
    rng = np.random.default_rng(71)
    expected_rng = np.random.default_rng(71)
    expected_rng.integers(0, 2**31 - 1)
    result = model.forecast(h, 4, 2, rng)
    assert result.inflow is engine.result.inflow
    assert rng.bit_generator.state == expected_rng.bit_generator.state

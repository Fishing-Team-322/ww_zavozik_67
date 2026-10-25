"""Serving wrappers for the event models: adapter, shapes, chunking, confidence."""
import sys
from datetime import date, timedelta

import numpy as np
import pytest

from zavozik_ml import forecasters
from zavozik_ml.forecasters import models  # noqa: F401 - populates the registry
from zavozik_ml.forecasters import event_models as em
from zavozik_ml.forecasters.base import AUTO_PREFERENCE, History


def make_history(days=200, missing_days=0, zero=False, seed=3):
    rng = np.random.default_rng(seed)
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(days)]
    work = np.array([d.weekday() < 5 for d in dates])
    inflow = np.where(work, rng.gamma(3, 200.0, days), 0.0) if not zero else np.zeros(days)
    outflow = np.where(work, rng.gamma(2, 150.0, days), 0.0) if not zero else np.zeros(days)
    missing = np.zeros(days, dtype=bool)
    if missing_days:
        missing[-missing_days:] = True
        inflow[missing] = 0.0
        outflow[missing] = 0.0
    return History(dates=dates, inflow=inflow, outflow=outflow, missing=missing,
                   industry="test", categories={})


def test_adapter_keeps_daily_totals_and_flags_unknown_days():
    history = make_history(days=60, missing_days=3)
    adapted = em.history_to_events(history)
    assert len(adapted.dates) == 60
    assert not adapted.known[-3:].any(), "known missing days must be unknown, not silent"
    daily = adapted.daily_amounts
    for day in range(57):
        assert daily[day, 0] == pytest.approx(history.inflow[day])
        assert daily[day, 1] == pytest.approx(history.outflow[day])
    assert len(adapted.events) == int((history.inflow[:57] > 0).sum() + (history.outflow[:57] > 0).sum())


def test_adapter_rejects_empty_history():
    with pytest.raises(ValueError, match="non-empty"):
        em.history_to_events(History(dates=[], inflow=np.array([]), outflow=np.array([]),
                                     missing=np.array([], dtype=bool), industry="x"))


@pytest.mark.parametrize("name", ["event_blocks", "event_hybrid"])
def test_wrappers_return_valid_paths_for_short_and_long_horizons(name):
    model = forecasters.get(name)
    history = make_history()
    for horizon in (7, 30, 90):
        paths = model.forecast(history, horizon, 40, np.random.default_rng(1))
        assert paths.inflow.shape == paths.outflow.shape == (40, horizon)
        assert np.isfinite(paths.inflow).all() and np.isfinite(paths.outflow).all()
        assert (paths.inflow >= 0).all() and (paths.outflow >= 0).all()
        if horizon > 30:
            assert paths.low_confidence, "beyond the native 30-day horizon must be flagged"


@pytest.mark.parametrize("name", ["event_blocks", "event_hybrid"])
def test_wrappers_are_deterministic(name):
    model = forecasters.get(name)
    history = make_history()
    a = model.forecast(history, 30, 25, np.random.default_rng(7))
    b = model.forecast(history, 30, 25, np.random.default_rng(7))
    np.testing.assert_array_equal(a.inflow, b.inflow)
    np.testing.assert_array_equal(a.outflow, b.outflow)


@pytest.mark.parametrize("name", ["event_blocks", "event_hybrid"])
def test_generated_events_reconcile_with_returned_paths(name):
    model = forecasters.get(name)
    history = make_history()
    events = em.history_to_events(history)
    fitted = model._fitted(history)
    raw = fitted.sample(events, 30, 20, np.random.default_rng(2))
    paths = em.events_to_paths(raw, 20, 30)
    np.testing.assert_allclose(paths.inflow, paths.outflow * 0 + paths.inflow)
    # Rebuild from the event ledger: per path/day sums must match the served arrays.
    ledger = raw.events
    for path in range(20):
        for day in range(1, 31):
            rows = ledger[(ledger.path == path) & (ledger.day == day)]
            assert paths.inflow[path, day - 1] == pytest.approx(rows.loc[rows.direction == 0, "amount"].sum())
            assert paths.outflow[path, day - 1] == pytest.approx(rows.loc[rows.direction == 1, "amount"].sum())


@pytest.mark.parametrize("name", ["event_blocks", "event_hybrid"])
def test_short_history_sets_low_confidence(name):
    paths = forecasters.get(name).forecast(make_history(days=20), 30, 10, np.random.default_rng(0))
    assert paths.low_confidence


@pytest.mark.parametrize("name", ["event_blocks", "event_hybrid"])
def test_observed_silence_returns_zeros(name):
    paths = forecasters.get(name).forecast(make_history(zero=True), 30, 8, np.random.default_rng(0))
    assert not paths.inflow.any() and not paths.outflow.any()
    assert paths.low_confidence


def test_registry_and_auto_preference_are_unchanged():
    assert "event_blocks" not in AUTO_PREFERENCE and "event_hybrid" not in AUTO_PREFERENCE
    assert forecasters.get("event_blocks").name == "event_blocks"
    assert forecasters.get("event_hybrid").name == "event_hybrid"
    assert forecasters.default_model() != "event_blocks"


def test_registering_event_models_does_not_import_torch():
    # Subprocess: another test module in the same session may import torch.
    import subprocess
    code = ("import sys; import zavozik_ml.forecasters.models; "
            "assert 'torch' not in sys.modules, 'forecasters pulled in torch'")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env={**__import__("os").environ, "PYTHONPATH": "ml"})
    assert result.returncode == 0, result.stderr


def test_sampling_300_paths_stays_fast():
    import time
    model = forecasters.get("event_hybrid")
    history = make_history(days=120)
    tick = time.monotonic()
    model.forecast(history, 30, 300, np.random.default_rng(0))
    assert time.monotonic() - tick < 5.0

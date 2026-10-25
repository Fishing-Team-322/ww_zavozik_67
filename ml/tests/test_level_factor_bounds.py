"""Pins the level-correction bounds and the minimum-support threshold for both models.

Review note: the existing suites exercise stationary and mild-drift cases, which do
not fail if clipping or the eight-positive threshold is removed. These tests use
saturating and boundary fixtures so those guards are actually pinned.
"""
import numpy as np
import pandas as pd
import pytest

from zavozik_ml.event_forecasters import blocks, hybrid
from zavozik_ml.event_forecasters.core import EventHistory

DAYS = 200
COLUMNS = ["date", "direction", "amount", "category", "counterparty"]


def history(entries):
    """entries: list of (day_offset, direction, amount)."""
    dates = np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + np.timedelta64(DAYS, "D"))
    rows = [dict(date=pd.Timestamp(dates[offset]), direction=direction, amount=amount,
                 category="supplier", counterparty="c") for offset, direction, amount in entries]
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return EventHistory("level-bounds", "industry", dates, np.zeros(DAYS, dtype=bool),
                        np.full(DAYS, np.datetime64("NaT", "D")), frame)


def drifted(recent_amount):
    baseline = [(offset, 1, 1000.0) for offset in range(0, 100)]      # older than the 91-day window
    recent = [(offset, 1, recent_amount) for offset in range(110, 130)]
    return history(baseline + recent)


@pytest.mark.parametrize("model", [blocks, hybrid])
def test_one_way_downward_correction_saturates_at_the_lower_bound(model):
    assert model._level_factor(drifted(100.0), 1) == pytest.approx(0.8, abs=1e-9)


@pytest.mark.parametrize("model", [blocks, hybrid])
def test_explosive_upward_drift_saturates_at_the_upper_bound(model):
    assert model._level_factor(drifted(10000.0), 1) == pytest.approx(1.25, abs=1e-9)


@pytest.mark.parametrize("model", [blocks, hybrid])
def test_seven_recent_positives_are_not_enough_but_eight_are(model):
    baseline = [(offset, 1, 1000.0) for offset in range(0, 100)]
    seven = [(offset, 1, 2000.0) for offset in range(110, 117)]
    assert model._level_factor(history(baseline + seven), 1) == pytest.approx(1.0, abs=1e-12)
    eight = seven + [(117, 1, 2000.0)]
    factor = model._level_factor(history(baseline + eight), 1)
    assert 1.0 < factor < 1.25, "with eight positives the shrunk factor must be applied, not clipped"

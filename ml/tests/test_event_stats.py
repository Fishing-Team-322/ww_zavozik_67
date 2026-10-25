import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
spec = importlib.util.spec_from_file_location("event_stats", Path(__file__).parents[1] / "experiments/event_stats.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def frame():
    rows = []
    rng = np.random.default_rng(0)
    for company in ("A", "B", "C", "D"):
        for origin in (1, 2):
            good = 10.0 + rng.random()
            for model, value in (("better", good), ("worse", 20.0 + rng.random())):
                if model == "better":
                    probability = 1.0 if company in ("A", "B") else 0.0
                else:
                    probability = 0.9 if company in ("A", "B") else 0.1
                rows.append(dict(cohort="unseen", company_id=company, origin=f"o{origin}",
                                 model=model, net_path_mae=value,
                                 gap_probability=probability,
                                 gap_actual=company in ("A", "B")))
    return pd.DataFrame(rows)


def test_paired_ratio_detects_real_improvement_with_ci_below_one():
    result = m.paired_ratio(frame(), "unseen", "net_path_mae", "better", "worse", repeats=500)
    assert result["ratio"] < 0.6
    assert result["ci_high"] < 1.0
    assert result["p_better"] == 1.0
    assert result["companies"] == 4 and result["origins"] == 8


def test_paired_ratio_rejects_missing_model():
    with pytest.raises(ValueError, match="missing model"):
        m.paired_ratio(frame(), "unseen", "net_path_mae", "better", "absent", repeats=10)


def test_gap_calibration_skill_and_ece():
    good = m.gap_calibration(frame(), "unseen", "better")
    bad = m.gap_calibration(frame(), "unseen", "worse")
    assert good["events"] == 4 and good["origins"] == 8
    assert good["base_rate"] == 0.5
    assert good["brier_skill"] > bad["brier_skill"]
    assert 0.0 <= good["ece"] <= 1.0
    assert sum(b["n"] for b in good["reliability"]) == good["origins"]


def test_gap_calibration_rejects_unscored_model():
    with pytest.raises(ValueError, match="no scored gaps"):
        m.gap_calibration(frame(), "unseen", "absent")

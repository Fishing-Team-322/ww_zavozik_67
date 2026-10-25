"""Tests for the ablation summary table."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
spec = importlib.util.spec_from_file_location("ablation_summary", Path(__file__).parents[1] / "experiments/ablation_summary.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def frame(models, scale):
    rows = []
    for company in ("A", "B", "C", "D"):
        for origin in ("2026-03-31", "2026-04-30"):
            for model in models:
                rows.append(dict(cohort="unseen", company_id=company, origin=origin, model=model,
                                 net_path_mae=scale * (1 + 0.1 * (company == "B")),
                                 net_mae_7=scale, net_mae_14=scale, net_mae_30=scale,
                                 net_pinball=scale / 10, net_width=scale * 100,
                                 net_coverage=0.9 if scale > 1 else 0.8,
                                 gap_brier=0.2 if scale > 1 else 0.15))
    return pd.DataFrame(rows)


def test_variant_improvement_is_reported_with_interval():
    baseline = frame(["blocks"], 1.0).assign(model="blocks_baseline")
    variant = frame(["blocks"], 0.9).assign(model="blocks_variant")
    table = m.summarise(baseline, variant, repeats=300)
    main = table[table.metric == "net_path_mae"].iloc[0]
    assert main.model == "blocks"
    assert main.ratio == pytest.approx(0.9)
    assert main.ci_high < 1.0 and main.p_better > 0.9
    assert main.baseline == pytest.approx(baseline.net_path_mae.mean())
    assert main.variant == pytest.approx(variant.net_path_mae.mean())
    assert main.variant < main.baseline
    coverage = table[table.metric == "net_coverage"].iloc[0]
    assert np.isnan(coverage.ratio)
    assert coverage.baseline == pytest.approx(baseline.net_coverage.mean())
    assert coverage.variant == pytest.approx(variant.net_coverage.mean())


def test_missing_columns_are_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame([dict(cohort="unseen", model="m")]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        m.load(path, "_baseline")


def test_suffixes_are_applied_to_model_names(tmp_path):
    path = tmp_path / "origins.csv"
    frame(["blocks"], 1.0).to_csv(path, index=False)
    assert set(m.load(path, "_variant").model) == {"blocks_variant"}

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
spec = importlib.util.spec_from_file_location("option_eval", Path(__file__).parents[1] / "experiments/option_eval.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_default_seed_falls_back_to_reference_config():
    assert m.seeds_for(42, []) == [42]
    assert m.seeds_for(42, [7, 8]) == [7, 8]


def test_origins_are_the_out_of_fit_month_ends():
    assert m.ORIGINS == ("2026-03-31", "2026-04-30", "2026-05-31")
    assert all(origin < "2026-07-01" for origin in m.ORIGINS)


def test_build_returns_fitted_model_with_required_api():
    from tests.event_forecaster_fixtures import histories
    model = m.build("blocks", histories(3, 240))
    assert hasattr(model, "sample")


def test_results_carry_the_cohort_column_summarize_needs():
    import pandas as pd
    from tests.event_forecaster_fixtures import histories
    model = m.build("blocks", histories(3, 240))
    history = histories(1, 240)[0].prefix(histories(1, 240)[0].as_of)
    paths = model.sample(history, 30, 5, __import__("numpy").random.default_rng(0))
    assert paths.n_paths == 5
    frame = pd.DataFrame([dict(cohort="unseen", model="blocks", origins=1)])
    assert "cohort" in frame

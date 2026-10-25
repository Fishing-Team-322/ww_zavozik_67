import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
spec = importlib.util.spec_from_file_location("event_adjust", Path(__file__).parents[1] / "experiments/event_adjust.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_monthly_origins_are_month_ends_within_bounds():
    origins = m.monthly_origins("2025-07-01", "2025-10-31")
    assert origins == ["2025-07-31", "2025-08-31", "2025-09-30", "2025-10-31"]


def test_scale_paths_keeps_median_and_scales_deviation():
    flows = np.zeros((4, 3, 2))
    flows[:, :, 0] = np.array([[10., 20., 30.]] * 4)
    flows[:, :, 1] = np.array([[5., 5., 5.]] * 4)
    flows[0, 0, 0], flows[3, 0, 0] = 0., 20.
    scaled = m.scale_paths(flows, 2.0)
    assert (scaled >= 0).all() and np.isfinite(scaled).all()
    np.testing.assert_allclose(np.median(scaled, axis=0), np.median(flows, axis=0))
    assert scaled[3, 0, 0] - np.median(flows, axis=0)[0, 0] == pytest.approx(2 * (20. - 10.))
    with pytest.raises(ValueError):
        m.scale_paths(flows, 0)


def test_mixture_takes_whole_paths_in_fixed_shares():
    parts = {"blocks": np.full((300, 30, 2), 1.), "hybrid": np.full((300, 30, 2), 2.),
             "gbm_global": np.full((300, 30, 2), 3.)}
    mixed = m.mixture_paths(parts, 300)
    assert mixed.shape == (300, 30, 2)
    assert set(np.unique(mixed)) == {1., 2., 3.}
    assert (mixed == 1.).all(axis=(1, 2)).sum() == 100
    with pytest.raises(ValueError):
        m.mixture_paths(parts, 2)


def test_mixture_rejects_members_that_return_too_few_paths():
    parts = {"blocks": np.zeros((10, 30, 2)), "hybrid": np.zeros((10, 30, 2)),
             "gbm_global": np.zeros((10, 30, 2))}
    with pytest.raises(ValueError, match="produced"):
        m.mixture_paths(parts, 300)


def test_fit_spread_uses_calibration_companies_only():
    class Stub(m.Runner):
        def __init__(self, calibration):
            self.meta = {"calibration_ids": calibration, "test_ids": ["T1"]}
            company = lambda: type("C", (), {
                "origin": staticmethod(lambda origin: 0),
                "dates": np.zeros(m.reference.HORIZON + 2, dtype="datetime64[D]"),
                "missing": np.zeros(m.reference.HORIZON + 2, dtype=bool),
                "detected": np.full(m.reference.HORIZON + 2, np.datetime64("NaT", "D")),
            })()
            self.by_id = {cid: company() for cid in calibration}
            self.n_paths = 30
            self.seen, self.calibration_pairs, self.calibration_skips = [], 0, []

        def sample(self, cid, origin, models):
            if cid not in self.meta["calibration_ids"]:
                raise AssertionError(f"sampled non-calibration company {cid}")
            self.seen.append(cid)
            flows = np.zeros((30, m.reference.HORIZON, 2))
            flows[:, :, 0] = np.arange(30)[:, None] + 1.0
            daily = np.zeros((m.reference.HORIZON + 2, 2))
            daily[:, 0] = 1.0
            company = type("C", (), {"flows": daily})()
            return (company, 0, None,
                    {"blocks": (flows, None), "hybrid": (flows, None), "gbm_global": (flows, None)})

    runner = Stub(["C1", "C2"])
    factors, curves = m.Runner.fit_spread(runner, ["2025-06-30"])
    assert set(runner.seen) == {"C1", "C2"}
    assert runner.calibration_pairs == 2
    assert set(factors) == {"blocks", "hybrid", "mixture"}
    for values in curves.values():
        assert len(values) == len(m.SPREAD_GRID)
        assert all(0 <= v <= 1 for v in values.values())

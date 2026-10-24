import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.event_forecaster_fixtures import history
from zavozik_ml.event_forecasters.core import EventPaths

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
spec = importlib.util.spec_from_file_location("event_benchmark", Path(__file__).parents[1] / "experiments/event_benchmark.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def test_empirical_crps_matches_direct_pairwise_formula():
    samples = np.array([[0., 2.], [1., 4.], [3., 8.]])
    truth = np.array([1., 3.])
    expected = np.abs(samples - truth).mean(axis=0) - .5 * np.abs(samples[:, None] - samples[None, :]).mean(axis=(0, 1))
    np.testing.assert_allclose(m.crps(samples, truth), expected)
    assert not m.crps(np.repeat(truth[None], 3, axis=0), truth).any()
    with pytest.raises(ValueError):
        m.crps(np.array([[np.nan]]), [0.])


def test_energy_and_bins_preserve_zero_and_unbounded_tail():
    assert m.energy(np.ones((3, 4)), np.ones(4)) == 0
    assert m.energy(np.zeros((3, 4)), np.ones(4)) > 0
    h = history()
    paths = EventPaths.from_records(h, 30, 2, [
        dict(path=0, day=1, direction=0, amount=0., category="sales"),
        dict(path=0, day=1, direction=0, amount=.1, category="sales"),
        dict(path=1, day=2, direction=1, amount=1e20, category="novel"),
    ])
    bins = m.amount_bin_counts(paths.events, 2, 30)
    assert bins.sum() == 3
    assert bins[0, 0, 0, 0] == 1
    assert bins[0, 0, 0, 1] == 1
    assert bins[1, 1, 1, -1] == 1
    marks = m.marked_counts(paths.events, 2, 30, ["sales", "unknown"])
    assert marks[1, 1, 1, 1] == 1
    assert marks.sum() == 3


def test_common_scores_do_not_invent_event_or_count_predictions():
    h = history()
    o = 150
    flows = np.nan_to_num(h.daily_amounts[o + 1:o + 31])
    counts = np.nan_to_num(h.daily_counts[o + 1:o + 31])
    c = m.reference.Company(h.company_id, h.industry, h.dates, np.nan_to_num(h.daily_amounts),
                            np.nan_to_num(h.daily_counts), h.missing, h.detected,
                            np.full(len(h.dates), np.nan), np.zeros(len(h.dates)), h.events)
    sampled = np.repeat(flows[None], 3, axis=0)
    old = m.scores(c, o, sampled, h.prefix(h.dates[o]))
    assert old["daily_amount_crps"] == old["net_crps"] == old["net_path_mae"] == 0
    assert "count_crps" not in old and "marked_count_crps" not in old
    with_counts = m.scores(c, o, sampled, h.prefix(h.dates[o]), np.repeat(counts[None], 3, axis=0))
    assert with_counts["count_crps"] == with_counts["occurrence_brier"] == 0


def test_paired_cohorts_fail_if_a_model_is_missing_an_origin():
    rows = pd.DataFrame([dict(cohort="unseen", company_id="A", origin="2026-04-30", model="a"),
                         dict(cohort="unseen", company_id="A", origin="2026-04-30", model="b")])
    m.assert_paired(rows, ["a", "b"])
    with pytest.raises(ValueError, match="unpaired"):
        m.assert_paired(rows.iloc[:1], ["a", "b"])


def test_reference_metrics_allow_absence_of_count_output():
    h = history()
    c = m.reference.Company(h.company_id, h.industry, h.dates, h.daily_amounts, h.daily_counts,
                            h.missing, h.detected, np.full(len(h.dates), np.nan), np.zeros(len(h.dates)), h.events)
    output = m.reference.metrics(c, 150, np.repeat(h.daily_amounts[151:181][None], 3, axis=0))
    assert "count_abs_error" not in output and "count_actual" not in output
    assert output["net_path_mae"] == 0


def test_count_replay_rejects_changed_width_or_horizon_errors():
    import csv, tempfile
    from pathlib import Path
    rows = [dict(cohort="unseen", company_id="A", origin="2026-04-30", model="count_bootstrap",
                 flow_abs_error=1.0, count_abs_error=2.0, net_path_mae=3.0, net_mae_7=3.0,
                 net_mae_14=3.0, net_mae_30=3.0, net_pinball=4.0, net_coverage=.5,
                 net_width=5.0, gap_brier=.1)]
    def replay(changed):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "origins.csv"
            with old.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
            frame = pd.DataFrame([dict(rows[0], **changed)])
            m.verify_count_replay(frame, pd.read_csv(old))
    replay({})
    for key, value in (("net_width", 6.0), ("net_mae_30", 9.0), ("net_coverage", .9)):
        with pytest.raises(ValueError, match="count reference scores changed"):
            replay({key: value})

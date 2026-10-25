"""Regression tests for the standalone case-only experiment (not serving)."""
import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location(
    "case_counts", Path(__file__).parents[1] / "experiments/case_counts.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def company(cid="C001", n=240):
    dates = np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + np.timedelta64(n, "D"))
    work = m.cal.is_workday(dates)
    counts = np.column_stack([work * 2., work * 1.])
    amounts = np.array([100., 60.])
    flows = counts * amounts
    balance = 1000 + np.cumsum(flows[:, 0] - flows[:, 1])
    events = []
    for i in range(n):
        for k, direction in enumerate(m.DIRECTIONS):
            for _ in range(int(counts[i, k])):
                events.append(dict(company_id=cid, date=pd.Timestamp(dates[i]),
                                   direction=direction, amount=amounts[k]))
    return m.Company(cid, "industry", dates, flows, counts, np.zeros(n, dtype=bool),
                     np.full(n, np.datetime64("NaT", "D")), balance, np.zeros(n), pd.DataFrame(events))


def test_future_mutation_cannot_change_features_or_simulation():
    c = company()
    changed = copy.deepcopy(c)
    o = 150
    changed.flows[o + 1:] = 1e9
    changed.counts[o + 1:] = 1e6
    changed.events.loc[changed.events.date > pd.Timestamp(c.dates[o]), "amount"] = 1e12
    x, scale, mask = m.features(c, o, {})
    xx, ss, mm = m.features(changed, o, {})
    pd.testing.assert_frame_equal(x, xx)
    np.testing.assert_array_equal(scale, ss)
    np.testing.assert_array_equal(mask, mm)
    for mu in (None, np.ones((30, 2)) * mask[:, None]):
        for left, right in zip(m.simulate(c, o, 50, np.random.default_rng(4), mu, [.1, .1]),
                               m.simulate(changed, o, 50, np.random.default_rng(4), mu, [.1, .1])):
            np.testing.assert_array_equal(left, right)


def test_future_missing_discovery_not_visible_in_history():
    c = company()
    original = m.features(c, 150, {})[0]
    c.missing[130:140] = True
    c.detected[130:140] = c.dates[170]
    pd.testing.assert_frame_equal(original, m.features(c, 150, {})[0])
    assert c.known(180)[130:140].sum() == 0


def test_split_disjoint_deterministic_and_excludes_audit():
    cs = [company(f"C{i:03}", n=2) for i in range(40)]
    parts = m.partition(cs, {"C001", "C002"}, 30, 42)
    ids = [set(c.id for c in group) for group in parts]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    assert not set.union(*ids) & {"C001", "C002"}
    assert [[c.id for c in g] for g in parts] == [[c.id for c in g] for g in m.partition(cs, {"C001", "C002"}, 30, 42)]


def test_sampling_nonnegative_finite_and_matches_amounts():
    c = company()
    mask = m.features(c, 150, {})[2]
    mu = np.tile([2., 1.], (30, 1)) * mask[:, None]
    flows, counts = m.simulate(c, 150, 200, np.random.default_rng(3), mu, [.2, .2])
    assert flows.shape == counts.shape == (200, 30, 2)
    assert np.isfinite(flows).all() and (flows >= 0).all()
    np.testing.assert_allclose(flows, counts * [100, 60])
    assert not flows[:, ~mask].any()
    assert not counts[:, ~mask].any()


def test_cumulative_metrics_and_balance_reconciliation():
    c = company()
    o = 150
    truth = c.flows[o + 1:o + 31]
    counts = c.counts[o + 1:o + 31]
    scores = m.metrics(c, o, np.repeat(truth[None], 4, axis=0), np.repeat(counts[None], 4, axis=0))
    assert scores["flow_abs_error"] == scores["count_abs_error"] == scores["net_path_mae"] == 0
    assert scores["net_coverage"] == 1
    assert scores["gap_brier"] == 0
    c.balance[o + 3] += 100
    with pytest.raises(ValueError, match="reconciliation"):
        m.metrics(c, o, np.repeat(truth[None], 4, axis=0), np.repeat(counts[None], 4, axis=0))


def test_missing_future_cannot_be_evaluated():
    c = company()
    assert m.evaluable(c, 150)
    c.missing[160] = True
    assert not m.evaluable(c, 150)
    assert not m.evaluable(c, None)
    assert not m.evaluable(c, len(c.dates) - 10)


@pytest.mark.parametrize("zero_amount", [False, True])
def test_loader_accepts_zero_and_rejects_inconsistent_exports(tmp_path, zero_amount):
    c = company(n=10)
    if zero_amount:
        c.events.loc[len(c.events)] = dict(company_id=c.id, date=pd.Timestamp(c.dates[0]),
                                           direction="in", amount=0.)
    frame = pd.DataFrame(dict(company_id=c.id, industry=c.industry, date=c.dates,
                              inflow=c.flows[:, 0], outflow=c.flows[:, 1], missing=False,
                              missing_known_on=pd.NaT, balance=c.balance))
    f, e = tmp_path / "flows.csv", tmp_path / "events.csv"
    frame.to_csv(f, index=False)
    c.events.to_csv(e, index=False)
    loaded = m.load(f, e)
    assert len(loaded) == 1
    assert loaded[0].counts.sum() == len(c.events)
    frame.loc[0, "inflow"] += 100
    frame.to_csv(f, index=False)
    with pytest.raises(ValueError, match="reconcile"):
        m.load(f, e)


def test_training_and_saved_model_roundtrip(tmp_path):
    c = company(n=240)
    models, rows = m.train([c], "2025-07-01", {"industry": 0}, 5, 1, 42)
    assert rows > 0
    mu = m.expected(models, c, 190, {"industry": 0})
    assert np.isfinite(mu).all() and (mu >= 0).all()
    path = tmp_path / "model.txt"
    models[0].save_model(str(path))
    x, scale, mask = m.features(c, 190, {"industry": 0})
    restored = m.lgb.Booster(model_file=str(path))
    np.testing.assert_allclose(restored.predict(x) * scale[0] * mask, mu[:, 0])


def test_training_ignores_future_facts_and_future_gap_discoveries():
    c = company(n=240)
    changed = copy.deepcopy(c)
    cutoff = "2025-07-01"
    end = int(np.searchsorted(c.dates, np.datetime64(cutoff), side="right"))
    changed.counts[end:] = 1e6
    changed.flows[end:] = 1e12
    changed.missing[120:140] = True
    changed.detected[120:140] = c.dates[end + 10]
    left, nleft = m.train([c], cutoff, {}, 5, 1, 42)
    right, nright = m.train([changed], cutoff, {}, 5, 1, 42)
    assert nleft == nright
    x = m.features(c, 150, {})[0]
    for a, b in zip(left, right):
        np.testing.assert_array_equal(a.predict(x), b.predict(x))


def test_calibration_ignores_gap_discoveries_after_its_as_of_cutoff():
    class Predictor:
        def predict(self, x):
            return np.full(len(x), .5)

    c = company()
    models = [Predictor(), Predictor()]
    origin, cutoff = str(c.dates[150]), str(c.dates[180])
    before = m.dispersion(models, [c], origin, {}, as_of=cutoff)
    c.missing[160] = True
    c.detected[160] = c.dates[200]
    np.testing.assert_array_equal(before, m.dispersion(models, [c], origin, {}, as_of=cutoff))
    assert not m.evaluable(c, 150)  # retrospective truth scoring is different
    c.detected[160] = c.dates[175]
    with pytest.raises(ValueError, match="no calibration observations"):
        m.dispersion(models, [c], origin, {}, as_of=cutoff)
    with pytest.raises(ValueError, match="horizon must finish"):
        m.dispersion(models, [c], origin, {}, as_of=str(c.dates[170]))


def test_temporal_boundary_rejected_before_training(tmp_path):
    split = tmp_path / "split.json"
    split.write_text('{"audit_start":"2026-07-01","audit_companies":[]}')
    args = SimpleNamespace(out=tmp_path / "out", split=split,
                           calibration_origin="2026-03-31", test_origins=["2026-06-01"])
    with pytest.raises(ValueError, match="audit_start"):
        m.run(args)

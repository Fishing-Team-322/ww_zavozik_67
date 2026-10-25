import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "experiments"))
spec = importlib.util.spec_from_file_location("benchmark_export", Path(__file__).parents[1] / "experiments/benchmark_export.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


DOCS = {"cohorts": {"unseen": "held out"}, "metrics": {"net_path_mae": "rubles"}, "caveats": ["synthetic"]}


def make_run(root, name, rows, cohorts=None, status="ok"):
    directory = root / name
    directory.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(directory / "summary.csv", index=False)
    (directory / "metadata.json").write_text(json.dumps({"status": status}))
    return dict(name=name, dir=str(directory), cohorts=cohorts) if cohorts else dict(name=name, dir=str(directory))


def test_export_copies_values_and_records_provenance(tmp_path):
    run = make_run(tmp_path, "run-a", [
        dict(cohort="unseen", model="blocks", origins=27, companies=9, net_path_mae=881308.5,
             net_mae_vs_naive=0.784, net_coverage=0.895, net_pinball=311251.3),
        dict(cohort="seen_future", model="blocks", origins=300, companies=30, net_path_mae=1.0,
             net_mae_vs_naive=0.9, net_coverage=0.8, net_pinball=2.0)])
    spec_path = tmp_path / "runs.json"
    spec_path.write_text(json.dumps({"documentation": DOCS, "runs": [run]}))
    out = tmp_path / "out"
    record = m.export(spec_path, out)
    table = pd.read_csv(out / "model_benchmarks.csv")
    assert len(table) == 2 and record["rows"] == 2
    unseen = table[table.cohort == "unseen"].iloc[0]
    assert unseen.benchmark == "run-a" and unseen.model == "blocks"
    assert unseen.net_path_mae == pytest.approx(881308.5)
    assert unseen.net_mae_vs_naive == pytest.approx(0.784)
    assert record["runs"][0]["summary_sha256"] == m._sha256(Path(run["dir"]) / "summary.csv")
    assert record["runs"][0]["run_status"] == "ok"
    assert (out / "provenance.json").exists()


def test_export_filters_cohorts_without_losing_values(tmp_path):
    run = make_run(tmp_path, "run-b", [
        dict(cohort="unseen", model="m", origins=1, net_path_mae=1.0),
        dict(cohort="seen_future", model="m", origins=2, net_path_mae=2.0)], cohorts=["unseen"])
    spec_path = tmp_path / "runs.json"
    spec_path.write_text(json.dumps({"documentation": DOCS, "runs": [run]}))
    table = pd.read_csv(m.export(spec_path, tmp_path / "out") and tmp_path / "out" / "model_benchmarks.csv")
    assert set(table.cohort) == {"unseen"}
    assert table.origins.iloc[0] == 1


def test_export_rejects_missing_summary_and_bad_columns(tmp_path):
    spec_path = tmp_path / "runs.json"
    spec_path.write_text(json.dumps({"documentation": DOCS,
                                     "runs": [dict(name="gone", dir=str(tmp_path / "gone"))]}))
    with pytest.raises(ValueError, match="missing summary"):
        m.export(spec_path, tmp_path / "out")
    run = make_run(tmp_path, "bad", [dict(model="m")])
    spec_path.write_text(json.dumps({"documentation": DOCS, "runs": [run]}))
    with pytest.raises(ValueError, match="lacks columns"):
        m.export(spec_path, tmp_path / "out2")


def test_normalise_adds_missing_metric_columns_as_null():
    frame = m.normalise("x", pd.DataFrame([dict(cohort="unseen", model="m", origins=3)]))
    assert list(frame.columns) == list(m.KEEP)
    assert pd.isna(frame.gap_brier.iloc[0])


def test_export_requires_documentation_block(tmp_path):
    run = make_run(tmp_path, "run-c", [dict(cohort="unseen", model="m", origins=1)])
    spec_path = tmp_path / "runs.json"
    spec_path.write_text(json.dumps({"runs": [run]}))
    with pytest.raises(ValueError, match="must define"):
        m.export(spec_path, tmp_path / "out")
    spec_path.write_text(json.dumps({"documentation": {"cohorts": {}, "metrics": {}}, "runs": [run]}))
    with pytest.raises(ValueError, match="caveats"):
        m.export(spec_path, tmp_path / "out")

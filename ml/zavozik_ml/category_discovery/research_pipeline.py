"""One bounded, resumable public weak-supervision experiment. NO final audit.

Teacher train1000/calibration500, three frozen encoders' separate metric heads,
calibration agreement, then two extra seeds for the top two RESEARCH fits.
An immutable tracked-source snapshot is used for every subprocess. This never
activates a release, touches Go, reads final labels or declares production gates.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(value, indent=2)+"\n")
    temporary.replace(path)


def run(root: Path, out: Path):
    ml = root / "ml"
    data = ml / "data/category_discovery"
    corpus, review = data / "public_corpus_v1", data / "public_pair_review_v2"
    teacher = data / "teacher_base/50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b"
    train_python = ml / "data/chronos_venv/bin/python"
    teacher_python = data / "teacher_venv/bin/python"
    config = dict(scope="public multilingual budget WEAK research; no independent semantic accuracy",
        corpus_manifest_sha256=sha(corpus / "manifest.json"), review_manifest_sha256=sha(review / "manifest.json"),
        teacher_source_sha256=sha(teacher / "teacher_source.json"), limits=dict(train=1000, calibration=500),
        final_test_read=False, model_activation=False, seeds=[42,43,44])
    out.mkdir(parents=True, exist_ok=True)
    with (out / "controller.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("this research controller is already active") from None
        config_path = out / "config.json"
        snapshot = out / "source_snapshot"
        if config_path.exists():
            stored = json.loads(config_path.read_text())
            if stored["inputs"] != config:
                raise ValueError("research inputs/config changed")
            for name, expected in stored["source_files_sha256"].items():
                if sha(snapshot / name) != expected:
                    raise ValueError("immutable source snapshot changed")
        else:
            files = subprocess.check_output(["git", "ls-files", "ml/zavozik_ml/category_discovery", "ml/zavozik_ml/classify_v2", "ml/zavozik_ml/classify"], cwd=root, text=True).splitlines()
            files.append("ml/zavozik_ml/__init__.py")
            snapshot.mkdir(exist_ok=False)
            hashes = {}
            for name in sorted(set(files)):
                source = root / name
                relative = source.relative_to(ml)
                target = snapshot / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                hashes[str(relative)] = sha(target)
            write(config_path, dict(inputs=config, source_files_sha256=hashes,
                source_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()))
        state_path = out / "pipeline_state.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else dict(steps={})
        if state.get("phase") == "fits_complete_review_required":
            raise ValueError("bounded research fits already complete; review results, do not rerun")
        state.update(phase="running", controller_pid=os.getpid())
        write(state_path, state)
        env = dict(os.environ, PYTHONPATH=str(snapshot)+os.pathsep+str(ml/"gen"), HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", VECLIB_MAXIMUM_THREADS="2")
        def step(name, python, module, arguments, expected, *, resumable=False):
            branch = subprocess.check_output(["git","branch","--show-current"],cwd=root,text=True).strip()
            if branch != "ml":
                raise ValueError("work must remain in branch ml")
            if expected.is_file():
                previous = state["steps"].get(name, {})
                if previous.get("output_sha256") not in (None, sha(expected)):
                    raise ValueError("completed research output changed")
                state["steps"][name] = dict(status="complete", output_sha256=sha(expected))
                write(state_path, state)
                return
            if expected.parent.exists() and not resumable:
                raise ValueError(f"incomplete fit/evaluation preserved at {expected.parent}; repair exact failure before continuing")
            command = [str(python), "-m", "zavozik_ml.category_discovery."+module] + list(map(str, arguments))
            state.update(current_step=name, updated_unix=time.time())
            state["steps"][name] = dict(status="running", command=command)
            write(state_path, state)
            print(f"start {name}", flush=True)
            with (out / (name+".log")).open("a") as log:
                child = subprocess.Popen(command, cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT)
                state["steps"][name]["pid"] = child.pid
                write(state_path, state)
                status = child.wait()
            if status or not expected.is_file():
                raise RuntimeError(f"step {name} failed code{status}; preserve completed outputs")
            state["steps"][name] = dict(status="complete", output_sha256=sha(expected))
            write(state_path, state)
            print(f"complete {name}", flush=True)
        try:
            for part, limit in config["limits"].items():
                target = out / ("teacher_"+part)
                step("teacher_"+part, teacher_python, "batch_teacher", ["--review",review,"--partition",part,"--base",teacher,
                    "--out",target,"--limit",limit,"--batch-size",4], target/"report.json", resumable=True)
            tr, ca = out / "teacher_train/weak_pairs.jsonl", out / "teacher_calibration/weak_pairs.jsonl"
            def model_fit(name, seed):
                cache = data / "public_candidate_cache_v1" / name
                target = out / f"heads_{name}_seed{seed}"
                step(f"fit_{name}_{seed}", train_python, "train_metric_heads", ["--corpus",corpus,"--cache",cache,
                    "--train-labels",tr,"--calibration-labels",ca,"--out",target,"--allow-weak-supervision","--seed",seed], target/"manifest.json")
                evaluation = out / f"calibration_{name}_seed{seed}"
                step(f"cal_{name}_{seed}", train_python, "metric_evaluation", ["--corpus",corpus,"--cache",cache,
                    "--labels",ca,"--heads",target,"--out",evaluation,"--allow-weak-supervision"], evaluation/"report.json")
                return json.loads((evaluation / "report.json").read_text())
            reports = {name:model_fit(name, 42) for name in ("e5-small", "e5-base", "qwen3-embedding-0.6b")}
            ranking = sorted(reports, key=lambda name: (-reports[name]["comparisons"]["adapted"]["macro_average_precision"],name))
            selection = dict(scope="calibration-only WEAK label agreement; research comparison, NOT production model approval",
                ranking=ranking, seed42_macro_ap={n:reports[n]["comparisons"]["adapted"]["macro_average_precision"] for n in ranking},
                selected_before_extra_seeds=True, final_test_read=False, semantic_accuracy=None)
            selection_path = out / "research_selection.json"
            if selection_path.exists() and json.loads(selection_path.read_text()) != selection:
                raise ValueError("frozen research selection changed")
            write(selection_path, selection)
            for name in ranking[:2]:
                for seed in (43,44):
                    model_fit(name, seed)
            state.update(phase="fits_complete_review_required", current_step=None, updated_unix=time.time())
            write(state_path, state)
        except BaseException as exc:
            state.update(phase="failed", error=str(exc), updated_unix=time.time())
            write(state_path, state)
            raise
    return state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(run(a.root.resolve(), a.out.resolve()), indent=2))


if __name__ == "__main__":
    main()

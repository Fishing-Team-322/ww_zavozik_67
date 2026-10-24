"""Bounded offline batch proposals; same weak-label/evidence policy as teacher.

Batching is a distinct inference recipe, not a license to mix or relabel human
gold. A small parity/runtime smoke must precede a large annotation job.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import time

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows, write_rows
from .fetch_teacher import verify
from .local_teacher import SYSTEM, PROMPT_VERSION, parse_response, teacher_view, sha_of_row


def run(review: Path, partition: str, base: Path, out: Path, limit=1000, batch_size=4):
    if partition not in ("train", "calibration") or not 1 <= batch_size <= 4 or limit < 1:
        raise ValueError("train/calibration only, batch1..4, positive limit")
    meta = json.loads((review / "manifest.json").read_text())
    source = review / f"{partition}_blind.jsonl"
    if sha256_file(source) != meta["partitions"][partition]["blind_sha256"]:
        raise ValueError("review source changed")
    rows = read_rows(source)[:limit]
    if any(not re.fullmatch(r"[a-f0-9]{24}", r["pair_id"]) or "semantic_text" not in r["left"] or
           "semantic_text" not in r["right"] for r in rows):
        raise ValueError("bound hex pair ids and encoder-visible text required")
    teacher = verify(base)
    recipe = dict(label_provenance="local_model_weak_not_human_gold", independent_test=False, semantic_accuracy=None,
        teacher=teacher, source_sha256=sha256_file(source), prompt_version=PROMPT_VERSION, system_prompt=SYSTEM,
        partition=partition, limit=limit, batch_size=batch_size, max_tokens=256, temperature=0,
        prefill_step_size=1024, source_sha256s={name: sha256_file(Path(__file__).with_name(name))
                                              for name in ("batch_teacher.py", "local_teacher.py")})
    out.mkdir(parents=True, exist_ok=True)
    with (out / "writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("exact batch teacher run already active") from None
        started = out / "started.json"
        if started.exists():
            if json.loads(started.read_text()) != recipe:
                raise ValueError("batch teacher provenance changed; use a new run")
        else:
            started.write_text(json.dumps(recipe, ensure_ascii=False, indent=2)+"\n")
            for name in ("batch_teacher.py", "local_teacher.py"):
                shutil.copyfile(Path(__file__).with_name(name), out / (name+".txt"))
        if (out / "report.json").exists():
            raise ValueError("finished batch annotation; refuse duplicate inference")
        pairs = out / "pairs"
        pairs.mkdir(exist_ok=True)
        pending = []
        for r in rows:
            path = pairs / (r["pair_id"]+".json")
            if path.exists():
                result = json.loads(path.read_text())
                if result["input_sha256"] != sha_of_row(r):
                    raise ValueError("saved batch pair changed")
            else:
                pending.append(r)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from mlx_lm import load
        from mlx_lm.generate import batch_generate
        from mlx_lm.sample_utils import make_sampler
        model, tokenizer = load(str(base.resolve()), trust_remote_code=False,
                                tokenizer_config={"trust_remote_code": False, "local_files_only": True})
        for offset in range(0, len(pending), batch_size):
            current = pending[offset:offset+batch_size]
            prompts = []
            for r in current:
                message = {side: dict(direction=r[side]["direction"], purpose=teacher_view(r[side])) for side in ("left", "right")}
                prompts.append(tokenizer.apply_chat_template([{"role":"system", "content":SYSTEM},
                    {"role":"user", "content":json.dumps(message, ensure_ascii=False)}], add_generation_prompt=True, tokenize=True))
            begin = time.perf_counter()
            response = batch_generate(model, tokenizer, prompts, max_tokens=256, sampler=make_sampler(temp=0),
                completion_batch_size=batch_size, prefill_batch_size=batch_size, prefill_step_size=1024, verbose=False)
            seconds = time.perf_counter()-begin
            if len(response.texts) != len(current):
                raise ValueError("batch response cardinality mismatch")
            valid = 0
            for r, text in zip(current, response.texts):
                result = dict(pair_id=r["pair_id"], input_sha256=sha_of_row(r), raw_response=text,
                              seconds_amortized=seconds/len(current), batch_size=len(current), valid=False)
                try:
                    result["annotation"] = parse_response(text, r)
                    result["valid"] = True
                    valid += 1
                except (ValueError, TypeError, KeyError) as exc:
                    result["error"] = str(exc)
                target = pairs / (r["pair_id"]+".json")
                temporary = target.with_suffix(".partial")
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
                temporary.replace(target)
            print(f"{partition} batch {offset+len(current)}/{len(pending)} valid={valid}/{len(current)} {seconds:.2f}s peak={response.stats.peak_memory:.2f}GB", flush=True)
        results = [json.loads((pairs / (r["pair_id"]+".json")).read_text()) for r in rows]
        accepted = [r["annotation"] for r in results if r["valid"]]
        write_rows(out / "weak_pairs.jsonl", accepted)
        report = dict(partition=partition, proposed=len(rows), schema_valid=len(accepted), invalid=len(rows)-len(accepted),
            label_provenance="local_model_weak_not_human_gold", independent_test=False, semantic_accuracy=None,
            coarse=dict(Counter(r["coarse"] for r in accepted)), fine=dict(Counter(r["fine"] for r in accepted)),
            seconds_amortized=sum(r["seconds_amortized"] for r in results), batch_size=batch_size,
            weak_pairs_sha256=sha256_file(out / "weak_pairs.jsonl"), started_sha256=sha256_file(started))
        (out / "report.json").write_text(json.dumps(report, indent=2)+"\n")
        return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--review", type=Path, required=True)
    p.add_argument("--partition", choices=("train", "calibration"), required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int, default=1000)
    p.add_argument("--batch-size", type=int, default=4)
    a = p.parse_args()
    print(json.dumps(run(a.review, a.partition, a.base, a.out, a.limit, a.batch_size), indent=2))


if __name__ == "__main__":
    main()

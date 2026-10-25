"""Bounded larger-teacher OPEN diagnostic, never gold or automatic retraining.

Expected answers are never supplied to the teacher. Even passing them is only
a debugging gate. Keep weak provenance and exact encoder-visible evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import shutil
import time

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows, write_rows
from .fetch_research_teacher import verify, MODEL, REVISION
from .local_teacher import SYSTEM, PROMPT_VERSION, parse_response, sha_of_row, teacher_view
from .relation_policy import policy as relation_policy


def run(inputs: Path, base: Path, out: Path, *, policy="v2"):
    system,prompt_version=relation_policy(policy)
    meta=json.loads((inputs/"manifest.json").read_text())
    source=inputs/"train_blind.jsonl"
    if meta["source"]!="agent_authored_open_development_diagnostics" or meta["independent_test"] is not False:
        raise ValueError("open debugging inputs required; never claim independent gold")
    if sha256_file(source)!=meta["partitions"]["train"]["blind_sha256"]:
        raise ValueError("diagnostic source changed")
    expected_path=inputs/"private_expected.jsonl"
    expected_sha=sha256_file(expected_path)
    if expected_sha!=meta["expected_sha256"]:
        raise ValueError("open diagnostic expectations changed")
    rows=read_rows(source)
    if not 1<=len(rows)<=64 or any(r["partition"]!="train" for r in rows):
        raise ValueError("bounded train-only open diagnostic required")
    if any(len(r["pair_id"])!=24 or any(c not in "0123456789abcdef" for c in r["pair_id"]) for r in rows):
        raise ValueError("bound hex pair ids required")
    if len({r["pair_id"] for r in rows})!=len(rows):
        raise ValueError("duplicate pilot pair")
    teacher=verify(base)
    recipe=dict(teacher=teacher,prompt_version=prompt_version,system_prompt=system,
        source_sha256=sha256_file(source),inputs_manifest_sha256=sha256_file(inputs/"manifest.json"),
        expected_sha256=expected_sha,
        max_tokens=384,temperature=0,enable_thinking=False,maximum_mlx_memory_bytes=7*2**30,
        labels="local_model_weak_not_human_gold",purpose="open diagnostic; no fit/model activation",
        code_sha256={n:sha256_file(Path(__file__).with_name(n)) for n in
                     ("teacher_pilot.py","local_teacher.py","fetch_research_teacher.py","relation_policy.py")})
    out.mkdir(parents=True,exist_ok=True)
    with (out/"writer.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (out/"report.json").exists():
            raise ValueError("pilot finished; refuse duplicate inference")
        started=out/"started.json"
        if started.exists():
            if json.loads(started.read_text())!=recipe:
                raise ValueError("pilot recipe changed; preserve outputs")
        else:
            started.write_text(json.dumps(recipe,ensure_ascii=False,indent=2)+"\n")
            for n in recipe["code_sha256"]:
                shutil.copyfile(Path(__file__).with_name(n),out/(n+".txt"))
        pairs=out/"pairs"; pairs.mkdir(exist_ok=True)
        os.environ["HF_HUB_OFFLINE"]="1";os.environ["TRANSFORMERS_OFFLINE"]="1"
        import mlx.core as mx
        from mlx_lm import load,generate
        from mlx_lm.sample_utils import make_sampler
        mx.set_memory_limit(recipe["maximum_mlx_memory_bytes"])
        mx.set_cache_limit(256*2**20)
        model,tokenizer=load(str(base.resolve()),trust_remote_code=False,
            tokenizer_config={"trust_remote_code":False,"local_files_only":True})
        for i,row in enumerate(rows):
            path=pairs/(row["pair_id"]+".json")
            if path.exists():
                if json.loads(path.read_text())["input_sha256"]!=sha_of_row(row):
                    raise ValueError("saved pilot input changed")
                continue
            messages=[{"role":"system","content":system},{"role":"user","content":json.dumps(
                {s:dict(direction=row[s]["direction"],purpose=teacher_view(row[s])) for s in ("left","right")},ensure_ascii=False)}]
            prompt=tokenizer.apply_chat_template(messages,add_generation_prompt=True,tokenize=False,enable_thinking=False)
            begin=time.perf_counter()
            text=generate(model,tokenizer,prompt=prompt,max_tokens=384,sampler=make_sampler(temp=0),verbose=False)
            result=dict(pair_id=row["pair_id"],input_sha256=sha_of_row(row),raw_response=text,
                        seconds=time.perf_counter()-begin,valid=False)
            try:
                result["annotation"]=parse_response(text,row,reviewer=MODEL+"@"+REVISION,prompt_version=prompt_version)
                result["valid"]=True
            except (ValueError,TypeError,KeyError) as exc:
                result["error"]=str(exc)
            temporary=path.with_suffix(".partial")
            temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");temporary.replace(path)
            print(f"pilot {i+1}/{len(rows)} valid={result['valid']} {result['seconds']:.2f}s",flush=True)
        results=[json.loads((pairs/(r["pair_id"]+".json")).read_text()) for r in rows]
        accepted=[r["annotation"] for r in results if r["valid"]]
        write_rows(out/"weak_pairs.jsonl",accepted)
        # Only now read open authored expectations, after all predictions exist.
        if sha256_file(expected_path)!=expected_sha:
            raise ValueError("open expectations changed during inference")
        keys={r["pair_id"]:r for r in read_rows(expected_path)}
        if set(keys)!={r["pair_id"] for r in rows}:
            raise ValueError("open expectation/input identities do not match")
        cases=[dict(keys[r["pair_id"]],actual=r[keys[r["pair_id"]]["level"]],
                    observed=r[keys[r["pair_id"]]["level"]]==keys[r["pair_id"]]["expected"]) for r in accepted]
        report=dict(status="open_diagnostic_only_not_a_validated_teacher",proposed=len(rows),schema_valid=len(accepted),
            expected_relation_count=sum(r["observed"] for r in cases),cases=cases,
            invalid=len(rows)-len(accepted),errors=dict(Counter(r.get("error") for r in results if not r["valid"])),
            semantic_accuracy=None,independent_test=False,final_test_read=False,fit_started=False,
            weak_pairs_sha256=sha256_file(out/"weak_pairs.jsonl"),started_sha256=sha256_file(started),
            peak_mlx_memory_bytes=mx.get_peak_memory(),seconds=sum(r["seconds"] for r in results))
        (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("inputs","base","out"):p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--policy",choices=("v2","v3"),default="v2")
    a=p.parse_args();print(json.dumps(run(a.inputs,a.base,a.out,policy=a.policy),indent=2))


if __name__=="__main__":
    main()

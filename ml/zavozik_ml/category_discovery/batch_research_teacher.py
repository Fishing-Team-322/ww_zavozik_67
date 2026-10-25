"""Resumable train/calibration annotation with the pinned larger local teacher.

All judgments remain WEAK. No final annotation, automatic relabeling of invalid
responses, training, or model activation. A batch parity pilot must precede use.
"""
from __future__ import annotations

import argparse
import copy
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


def run(review: Path, partition: str, base: Path, out: Path, *, limit=1000, batch_size=4, policy="v2", prefix_cache=False):
    system,prompt_version=relation_policy(policy)
    if partition not in ("train","calibration") or not 1<=limit<=5000 or not 1<=batch_size<=4:
        raise ValueError("bounded train/calibration only, batch1..4")
    if prefix_cache and batch_size!=1:raise ValueError("prefix cache uses serial inference only")
    meta=json.loads((review/"manifest.json").read_text());source=review/(partition+"_blind.jsonl")
    if sha256_file(source)!=meta["partitions"][partition]["blind_sha256"]:
        raise ValueError("pair review changed")
    rows=read_rows(source)[:limit]
    if any(r["partition"]!=partition or len(r["pair_id"])!=24 or
           any(c not in "0123456789abcdef" for c in r["pair_id"]) for r in rows):
        raise ValueError("bound hex training/calibration pairs required")
    if len({r["pair_id"] for r in rows})!=len(rows):
        raise ValueError("duplicate annotation pair")
    teacher=verify(base)
    recipe=dict(teacher=teacher,partition=partition,limit=limit,batch_size=batch_size,
        source_sha256=sha256_file(source),prompt_version=prompt_version,system_prompt=system,
        max_tokens=384,temperature=0,enable_thinking=False,memory_limit_bytes=7*2**30,prefix_cache=prefix_cache,
        label_provenance="local_model_weak_not_human_gold",semantic_accuracy=None,
        code_sha256={n:sha256_file(Path(__file__).with_name(n)) for n in
                     ("batch_research_teacher.py","fetch_research_teacher.py","local_teacher.py","relation_policy.py")})
    out.mkdir(parents=True,exist_ok=True)
    with (out/"writer.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (out/"report.json").exists():
            raise ValueError("annotation complete; refuse duplicate inference")
        started=out/"started.json"
        if started.exists():
            if json.loads(started.read_text())!=recipe:
                raise ValueError("annotation recipe changed; preserve output")
        else:
            started.write_text(json.dumps(recipe,ensure_ascii=False,indent=2)+"\n")
            for n in recipe["code_sha256"]:shutil.copyfile(Path(__file__).with_name(n),out/(n+".txt"))
        pairs=out/"pairs";pairs.mkdir(exist_ok=True);pending=[]
        for row in rows:
            path=pairs/(row["pair_id"]+".json")
            if path.exists():
                if json.loads(path.read_text())["input_sha256"]!=sha_of_row(row):
                    raise ValueError("saved annotation input changed")
            else:pending.append(row)
        os.environ["HF_HUB_OFFLINE"]="1";os.environ["TRANSFORMERS_OFFLINE"]="1"
        import mlx.core as mx
        from mlx_lm import load,generate
        from mlx_lm.generate import batch_generate
        from mlx_lm.models.cache import make_prompt_cache
        from mlx_lm.sample_utils import make_sampler
        mx.set_memory_limit(recipe["memory_limit_bytes"]);mx.set_cache_limit(256*2**20)
        model,tokenizer=load(str(base.resolve()),trust_remote_code=False,
            tokenizer_config={"trust_remote_code":False,"local_files_only":True})
        all_prompts={}
        for row in pending:
            messages=[{"role":"system","content":system},{"role":"user","content":json.dumps(
                {s:dict(direction=row[s]["direction"],purpose=teacher_view(row[s])) for s in ("left","right")},ensure_ascii=False)}]
            all_prompts[row["pair_id"]]=tokenizer.apply_chat_template(messages,add_generation_prompt=True,tokenize=True,enable_thinking=False)
        prefix=[];cached=None;prefill_seconds=0
        if prefix_cache and all_prompts:
            values=list(all_prompts.values());shortest=min(map(len,values))
            for i in range(shortest):
                if any(v[i]!=values[0][i] for v in values):break
                prefix.append(values[0][i])
            # Always leave input tokens to generation; don't consume its final
            # prompt token when all selected prompts happen to be identical.
            prefix=prefix[:shortest-1];cached=make_prompt_cache(model);begin=time.perf_counter()
            for start in range(0,len(prefix),512):
                mx.eval(model(mx.array([prefix[start:start+512]]),cache=cached))
                mx.eval([c.state for c in cached])
            prefill_seconds=time.perf_counter()-begin
            print("shared prefix",len(prefix),"tokens",prefill_seconds,"s",flush=True)
        for offset in range(0,len(pending),batch_size):
            current=pending[offset:offset+batch_size];prompts=[]
            for row in current:
                prompts.append(all_prompts[row["pair_id"]])
            begin=time.perf_counter()
            if prefix_cache:
                texts=[generate(model,tokenizer,prompt=prompts[0][len(prefix):],prompt_cache=copy.deepcopy(cached),
                    max_tokens=384,sampler=make_sampler(temp=0),verbose=False)]
            else:
                response=batch_generate(model,tokenizer,prompts,max_tokens=384,sampler=make_sampler(temp=0),
                    completion_batch_size=batch_size,prefill_batch_size=batch_size,prefill_step_size=1024,verbose=False)
                texts=response.texts
            seconds=time.perf_counter()-begin
            if len(texts)!=len(current):raise ValueError("batch cardinality mismatch")
            for row,text in zip(current,texts):
                result=dict(pair_id=row["pair_id"],input_sha256=sha_of_row(row),raw_response=text,
                            seconds_amortized=seconds/len(current),valid=False)
                try:
                    result["annotation"]=parse_response(text,row,reviewer=MODEL+"@"+REVISION,prompt_version=prompt_version)
                    result["valid"]=True
                except (ValueError,TypeError,KeyError) as exc:result["error"]=str(exc)
                target=pairs/(row["pair_id"]+".json");tmp=target.with_suffix(".partial")
                tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n");tmp.replace(target)
            print(partition,"pending",offset+len(current),"/",len(pending),f"{seconds:.2f}s",flush=True)
        results=[json.loads((pairs/(r["pair_id"]+".json")).read_text()) for r in rows]
        accepted=[r["annotation"] for r in results if r["valid"]];write_rows(out/"weak_pairs.jsonl",accepted)
        report=dict(partition=partition,proposed=len(rows),schema_valid=len(accepted),invalid=len(rows)-len(accepted),
            label_provenance="local_model_weak_not_human_gold",semantic_accuracy=None,independent_test=False,
            final_test_read=False,coarse=dict(Counter(r["coarse"] for r in accepted)),
            fine=dict(Counter(r["fine"] for r in accepted)),errors=dict(Counter(r.get("error") for r in results if not r["valid"])),
            seconds_amortized=sum(r["seconds_amortized"] for r in results),prefix_prefill_seconds=prefill_seconds,
            cached_prefix_tokens=len(prefix),peak_mlx_memory_bytes=mx.get_peak_memory(),
            weak_pairs_sha256=sha256_file(out/"weak_pairs.jsonl"),started_sha256=sha256_file(started))
        (out/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("review","base","out"):p.add_argument("--"+n,type=Path,required=True)
    p.add_argument("--partition",choices=("train","calibration"),required=True)
    p.add_argument("--limit",type=int,default=1000);p.add_argument("--batch-size",type=int,default=4)
    p.add_argument("--policy",choices=("v2","v3"),default="v2")
    p.add_argument("--prefix-cache",action="store_true")
    a=p.parse_args();print(json.dumps(run(a.review,a.partition,a.base,a.out,limit=a.limit,batch_size=a.batch_size,policy=a.policy,prefix_cache=a.prefix_cache),indent=2))


if __name__=="__main__":main()

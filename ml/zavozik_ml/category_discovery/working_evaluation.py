"""One frozen-release held-out coverage and local-teacher agreement audit.

This is a small, stratified weak audit. It cannot measure human semantic accuracy.
No labels or test predictions may feed inventory refinement or model selection.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows


def prepare(release, corpus, out):
    from .working_model import WorkingModel
    import numpy as np
    if out.exists():raise ValueError('heldout output exists; refuse repeat evaluation')
    # Selection precedes encoder inference and observes no judgments or scores.
    rows=read_rows(corpus/'test_unique.jsonl')
    order=lambda r:hashlib.sha256(('working-heldout-v1|'+r['content_key']).encode()).hexdigest()
    selected=sorted([r for r in rows if r['usable'] and r['source_domain']=='case'],key=order)
    selected+=sorted([r for r in rows if r['usable'] and r['source_domain']=='public'],key=order)[:64]
    out.mkdir(parents=True)
    protocol=dict(release_sha256=sha256_file(release/'release.json'),corpus_sha256=sha256_file(corpus/'manifest.json'),
        test_input_sha256=sha256_file(corpus/'test_unique.jsonl'),selected_keys=[r['content_key'] for r in selected],
        selection='all usable test case rows plus hash-first64 public test rows; no quality selection',
        maximum_teacher_pairs=32,teacher_pair_selection='hash-first covered operations; each predicted level compared with its least-similar training member',
        no_retuning_after_results=True,semantic_accuracy=None,human_gold=False)
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    model=WorkingModel(release);begin=time.perf_counter();x=model.encoder([r['semantic_text'] for r in selected])
    ops=[dict(id=r['id'],direction=r['direction']) for r in selected]
    assignments=model.assign_vectors(ops,[SimpleNamespace(usable=r['usable'],semantic_text=r['semantic_text']) for r in selected],x)
    np.save(out/'embeddings.npy',x,allow_pickle=False)
    (out/'selected_rows.json').write_text(json.dumps(selected,ensure_ascii=False)+'\n')
    (out/'assignments.json').write_text(json.dumps(assignments,ensure_ascii=False,indent=2)+'\n')
    from .metric_evaluation import project
    zs={level:project(x,model.weights,level) for level in ('coarse','fine')};pairs=[];key=[];per_group=Counter()
    for i,(r,a) in enumerate(zip(selected,assignments)):
        for level,identity in [('coarse',a.get('coarse_category_id')),('fine',a.get('category_id'))]:
            if not identity or per_group[identity]>=4 or len(pairs)>=32:continue
            n=next(n for n in model.nodes if n['id']==identity);scores=model.vectors[level][n['members']]@zs[level][i]
            member=n['members'][int(np.argmin(scores))];s=model.rows[member]
            pid=hashlib.sha256((r['content_key']+'|'+s['content_key']+'|'+level).encode()).hexdigest()[:24]
            fields=['content_key','id','direction','purpose','semantic_text']
            pairs.append(dict(schema='economic_pair_review_v2',partition='test',pair_id=pid,left={k:r[k] for k in fields},right={k:s[k] for k in fields},coarse=None,fine=None,rationale='',reviewer='',reviewer_kind=''))
            key.append(dict(pair_id=pid,level=level,operation_id=r['id'],category_id=identity));per_group[identity]+=1
    (out/'blind_pairs.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in pairs))
    (out/'sampling_key.json').write_text(json.dumps(key,indent=2)+'\n')
    coverage=dict(release_sha256=protocol['release_sha256'],cases=len(selected),sources=dict(Counter(r['source_domain'] for r in selected)),
        statuses=dict(Counter(a['status'] for a in assignments)),by_source={source:dict(Counter(a['status'] for r,a in zip(selected,assignments) if r['source_domain']==source)) for source in ['case','public']},
        teacher_pairs=len(pairs),seconds=time.perf_counter()-begin,independent_semantic_accuracy=None,
        warning='Coverage is not correctness; held-out rows but synthetic/public domain, local weak teacher not human gold')
    (out/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n');return coverage


def annotate(release, out, base):
    from .fetch_research_teacher import verify, MODEL, REVISION
    from .local_teacher import parse_response, teacher_view
    from .relation_policy import policy
    protocol=json.loads((out/'protocol.json').read_text())
    if sha256_file(release/'release.json')!=protocol['release_sha256']:raise ValueError('release changed since evaluation freeze')
    if (out/'teacher_report.json').exists():raise ValueError('heldout annotation finished; never repeat')
    rows=read_rows(out/'blind_pairs.jsonl');key={r['pair_id']:r for r in json.loads((out/'sampling_key.json').read_text())}
    if len(rows)>32 or any(r['partition']!='test' for r in rows):raise ValueError('bounded frozen test only')
    verify(base);system,version=policy('v3');os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    import mlx.core as mx
    from mlx_lm import load,generate
    from mlx_lm.models.cache import make_prompt_cache
    from mlx_lm.sample_utils import make_sampler
    mx.set_memory_limit(7*2**30);mx.set_cache_limit(256*2**20)
    model,tokenizer=load(str(base.resolve()),trust_remote_code=False,tokenizer_config={'trust_remote_code':False,'local_files_only':True})
    prompts=[tokenizer.apply_chat_template([{'role':'system','content':system},{'role':'user','content':json.dumps({s:dict(direction=r[s]['direction'],purpose=teacher_view(r[s])) for s in ['left','right']},ensure_ascii=False)}],add_generation_prompt=True,tokenize=True,enable_thinking=False) for r in rows]
    common=0
    if prompts:
        while common<min(map(len,prompts))-1 and all(p[common]==prompts[0][common] for p in prompts):common+=1
    cache=make_prompt_cache(model)
    for start in range(0,common,512):mx.eval(model(mx.array([prompts[0][start:min(start+512,common)]]),cache=cache));mx.eval([c.state for c in cache])
    results=[];directory=out/'teacher_pairs';directory.mkdir(exist_ok=True)
    for r,prompt in zip(rows,prompts):
        path=directory/(r['pair_id']+'.json')
        if path.exists():result=json.loads(path.read_text())
        else:
            text=generate(model,tokenizer,prompt=prompt[common:],prompt_cache=copy.deepcopy(cache),max_tokens=384,sampler=make_sampler(temp=0),verbose=False)
            result=dict(pair_id=r['pair_id'],raw_response=text,valid=False)
            try:result.update(valid=True,annotation=parse_response(text,r,reviewer=MODEL+'@'+REVISION,prompt_version=version))
            except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:result.update(valid=False,error=str(exc))
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)
        results.append(result);print('heldout teacher',len(results),'/',len(rows),'valid',result['valid'],flush=True)
    report=dict(release_sha256=protocol['release_sha256'],valid=sum(r['valid'] for r in results),proposed=len(rows),levels={},
        semantic_accuracy=None,human_gold=False,labels='local_model_weak_not_human',selection='conditional predicted-assignment audit; no population accuracy',
        peak_mlx_memory_bytes=mx.get_peak_memory(),teacher=MODEL+'@'+REVISION,prompt_version=version,
        blind_pairs_sha256=sha256_file(out/'blind_pairs.jsonl'),fit_or_selection_after_evaluation=False)
    for level in ['coarse','fine']:
        chosen=[r for r in results if key[r['pair_id']]['level']==level];counts=Counter(r['annotation'][level] if r['valid'] else 'schema_invalid' for r in chosen)
        report['levels'][level]=dict(counts,proposed=len(chosen))
    (out/'teacher_report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--phase',choices=['prepare','teacher'],required=True)
    for name in ['release','corpus','out','teacher_base']:p.add_argument('--'+name.replace('_','-'),type=Path)
    a=p.parse_args();r=prepare(a.release,a.corpus,a.out) if a.phase=='prepare' else annotate(a.release,a.out,a.teacher_base);print(json.dumps(r,indent=2))


if __name__=='__main__':main()

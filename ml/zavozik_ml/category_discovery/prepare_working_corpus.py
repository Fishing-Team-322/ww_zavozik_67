"""Prepare the source-bound case/public corpus before any new labels or fitting.

Preserves inherited company partitions, purges cross-source template/actual-token
collisions, and binds inherited vectors byte-for-byte. Only train/cal pair mining;
test input inspection is restricted to preparation and leakage checks.
"""
from pathlib import Path
import json,hashlib,itertools,random
from collections import defaultdict,Counter
import numpy as np
from transformers import AutoTokenizer
from zavozik_ml.category_discovery.preparation import Components,owner_for
from zavozik_ml.category_discovery.corpus import read_rows,write_rows
from zavozik_ml.classify_v2.splitting import signatures,TemplateIndex
from zavozik_ml.classify_v2.model import sha256_file
from zavozik_ml.category_discovery.semantic_pairs import endpoint,SCHEMA


def prepare(data, out):
    out.mkdir(parents=True,exist_ok=False)
    parts=('train','calibration','test');sources={'case':('corpus_economic_v4','candidate_cache_v2/qwen3-embedding-0.6b'),'public':('public_corpus_v1','public_candidate_cache_v1/qwen3-embedding-0.6b')};records=[];features={};lineage={}
    for domain,(cn,xn) in sources.items():
     corpus,cache=data/cn,data/xn;meta=json.loads((corpus/'manifest.json').read_text());cm=json.loads((cache/'manifest.json').read_text());assert cm['corpus_manifest_sha256']==sha256_file(corpus/'manifest.json');assert not any(n for checks in meta['intersections'].values() for n in checks.values());lineage[domain]=dict(corpus_sha=sha256_file(corpus/'manifest.json'),cache_sha=sha256_file(cache/'manifest.json'))
     for part in parts:
      path=corpus/(part+'_unique.jsonl');assert sha256_file(path)==meta[part]['unique_sha256'];rs=read_rows(path)
      if part!='test':assert sha256_file(cache/(part+'.npy'))==cm[part]['sha256'];x=np.load(cache/(part+'.npy'),allow_pickle=False)
      for i,r in enumerate(rs):
       r=dict(r,source_domain=domain,original_partition=part,company=domain+':'+r['company'],companies=[domain+':'+c for c in r['companies']],original_family=domain+':'+r['template_family']);records.append(r)
       if part!='test':features[r['content_key']]=x[i]
    recipe=cm['recipe'];base=data/'base/qwen3-embedding-0.6b/97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3';tok=AutoTokenizer.from_pretrained(base,local_files_only=True,trust_remote_code=False,padding_side='left');texts=sorted({r['semantic_text'] for r in records});tokenmap=dict(zip(texts,map(tuple,tok([recipe['prefix']+s for s in texts],truncation=True,max_length=256)['input_ids'])))
    components=Components();aliases={};first={}
    for r in records:
     k=r['content_key'];components.join(k,'family:'+r['original_family']);aliases[k]=signatures(r['purpose'])|signatures(r['semantic_text'])
     for a in aliases[k]:components.join(k,'alias:'+a)
     ids=tokenmap[r['semantic_text']];first.setdefault(ids,k);components.join(k,first[ids])
    aa={a for ss in aliases.values() for a in ss};index=TemplateIndex(aa)
    for a in sorted(aa):
     for b in index.matches(a):components.join('alias:'+a,'alias:'+b)
    eligible=defaultdict(set)
    for r in records:eligible[components.find(r['content_key'])].add(r['original_partition'])
    owners={k:owner_for(k,v,42) for k,v in eligible.items()};kept={p:[] for p in parts};purged=Counter();seen=set()
    for r in sorted(records,key=lambda x:(x['source_domain'],x['content_key'])):
     p=r['original_partition'];family=components.find(r['content_key']);density=(r['direction'],r['semantic_text'])
     if owners[family]!=p:purged[p]+=1;continue
     if density in seen:purged[p+':density_duplicate']+=1;continue
     seen.add(density);kept[p].append(dict(r,template_family='combined-leakage-'+hashlib.sha256(family.encode()).hexdigest()[:24]))
    sets={p:dict(companies={c for r in rs for c in r['companies']},families={r['template_family'] for r in rs},texts={r['semantic_text'] for r in rs},tokens={tokenmap[r['semantic_text']] for r in rs},aliases={a for r in rs for a in aliases[r['content_key']]}) for p,rs in kept.items()}
    intersections={f'{a}__{b}':{k:len(sets[a][k]&sets[b][k]) for k in sets[a]} for a,b in itertools.combinations(parts,2)}
    for a,b in itertools.combinations(parts,2):
     idx=TemplateIndex(sets[b]['aliases']);intersections[f'{a}__{b}']['near_template_pairs']=sum(len(idx.matches(t)) for t in sets[a]['aliases'])
    assert not any(v for ch in intersections.values() for v in ch.values()),intersections
    corpus,cache,review=[out/n for n in ['corpus','cache','review']]
    for q in [corpus,cache,review]:q.mkdir()
    meta=dict(protocol='combined_company_template_qwen_token_closure_v1',text_version='source_bound_case_public_semantic_v1',intersections=intersections,source_lineage=lineage,purged=dict(purged),source_kinds=['case_synthetic','public_multilingual_budget_auxiliary'],independent_test=False,test_preparation_only=True);cm=dict(model='qwen3-embedding-0.6b',recipe=recipe,base=cm['base'],text_version=meta['text_version'],source_lineage=lineage)
    for p,rs in kept.items():
     write_rows(corpus/(p+'_unique.jsonl'),rs);meta[p]=dict(unique=len(rs),unique_sha256=sha256_file(corpus/(p+'_unique.jsonl')),usable_unique=sum(r['usable'] for r in rs))
     if p!='test':
      x=np.stack([features[r['content_key']] for r in rs]);np.save(cache/(p+'.npy'),x,allow_pickle=False);cm[p]=dict(rows=len(rs),shape=list(x.shape),sha256=sha256_file(cache/(p+'.npy')),unique_sha256=meta[p]['unique_sha256'])
    (corpus/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n');cm['corpus_manifest_sha256']=sha256_file(corpus/'manifest.json');(cache/'manifest.json').write_text(json.dumps(cm,indent=2)+'\n')
    rmeta=dict(source='bounded_source_balanced_geometric_pair_review_not_gold',corpus_manifest_sha256=sha256_file(corpus/'manifest.json'),independent_test=False,partitions={},sampling='near/random stratified geometry; not population representative; before teacher labels')
    for part,counts in [('train',{'case':48,'public':64}),('calibration',{'case':16,'public':64})]:
     rs=kept[part];x=np.load(cache/(part+'.npy'));z=x-x.mean(0);z/=np.maximum(np.linalg.norm(z,axis=1,keepdims=True),1e-12);rng=random.Random('working-v1:'+part);chosen=[]
     for domain,total in counts.items():
      ids=[i for i,r in enumerate(rs) if r['usable'] and r['source_domain']==domain];xx=z[ids];cos=xx@xx.T;near=[]
      for local,i in enumerate(ids):
       for jl in np.argsort(-cos[local])[:32]:
        j=ids[int(jl)]
        if i<j and rs[i]['direction']==rs[j]['direction'] and rs[i]['template_family']!=rs[j]['template_family'] and rs[i]['company']!=rs[j]['company']:near.append((float(z[i]@z[j]),i,j))
      near=sorted(set(near),reverse=True);used=set();degree=Counter();target=total*3//4 if domain=='public' else total//2
      for score,i,j in near:
       if len(used)>=target:break
       if degree[i]>=3 or degree[j]>=3:continue
       used.add((i,j));degree[i]+=1;degree[j]+=1
      attempts=0
      while len(used)<total and attempts<100000:
       attempts+=1;i,j=sorted(rng.sample(ids,2))
       if rs[i]['direction']!=rs[j]['direction'] or rs[i]['template_family']==rs[j]['template_family'] or rs[i]['company']==rs[j]['company']:continue
       used.add((i,j))
      assert len(used)==total,(part,domain,len(used));chosen+=list(sorted(used))
     rng.shuffle(chosen);pairs=[]
     for i,j in chosen:
      a,b=rs[i],rs[j]
      if rng.random()<.5:a,b=b,a
      pid=hashlib.sha256('\0'.join(sorted([a['content_key'],b['content_key']])).encode()).hexdigest()[:24];pairs.append(dict(schema=SCHEMA,pair_id=pid,partition=part,left=endpoint(a),right=endpoint(b),coarse=None,fine=None,rationale='',reviewer='',reviewer_kind=''))
     write_rows(review/(part+'_blind.jsonl'),pairs);rmeta['partitions'][part]=dict(pairs=len(pairs),blind_sha256=sha256_file(review/(part+'_blind.jsonl')),source_counts=counts)
    (review/'manifest.json').write_text(json.dumps(rmeta,indent=2)+'\n');print(json.dumps(dict(output=str(out),parts={p:len(v) for p,v in kept.items()},purged=dict(purged),intersections=intersections,pairs={p:d['pairs'] for p,d in rmeta['partitions'].items()}),indent=2))


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();prepare(a.data,a.out)


if __name__=='__main__':main()

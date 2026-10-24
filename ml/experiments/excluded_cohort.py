"""Supplemental evaluation of the 13 companies outside the main calendar window.

The locked audit companies remain excluded from every fit. No tuning is done
from this supplemental report, and its numbers are not pooled into the audit.
"""
from pathlib import Path
from datetime import date
import hashlib,json,time
import numpy as np
import pandas as pd
from zavozik_ml import forecasters
from zavozik_ml.data import load_companies,DEFAULT_FLOWS
from zavozik_ml.eval.backtest import Config,AutoPolicy,make_origins,train_histories,evaluate_origin,summarize,_metrics
from zavozik_ml.forecasters import models
from zavozik_ml.provenance import source_fingerprint

root=Path(__file__).resolve().parents[1]
coverage=pd.read_csv(root/'reports/metrics/company_coverage.csv')
ids=set(coverage[coverage.evaluated_origins==0].company_id)
spec=json.loads((root/'eval/split_v1.json').read_text())
excluded=ids|set(spec['audit_companies'])
companies=load_companies()
cfg=Config(n_paths=600)
origins=[o for c in companies if c.id in ids for o in make_origins(c,cfg)]
cutoffs=sorted({o.as_of.replace(day=1) for o in origins})
source=source_fingerprint()
results=[]
selected=[forecasters.get(n) for n in ['seasonal_naive','gbm_global','ensemble']]+[AutoPolicy()]
for i,cutoff in enumerate(cutoffs):
 nxt=cutoffs[i+1] if i+1<len(cutoffs) else date.max
 batch=[o for o in origins if cutoff<=o.as_of<nxt]
 print(f'{cutoff}: {len(batch)} origins',flush=True)
 forecasters.get('gbm_global').fit(train_histories(companies,cutoff,excluded))
 for model in selected:
  for origin in batch:
   key=f'{cfg.seed}:{model.name}:{origin.company.id}:{origin.as_of}'
   seed=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'little')
   results.append(evaluate_origin(model,origin,cfg,np.random.default_rng(seed)))
summary=summarize(results,cfg,ids)
out=root/'data/supplemental_cohort.parquet'
flat=pd.DataFrame([{k:v for k,v in r.items() if k not in ('actual','adjusted','q','daily_gap_prob')}|
 {'h':h+1,'actual':r['actual'][h],'adjusted':r['adjusted'][h],'p10':r['q'][0,h],'p50':r['q'][1,h],'p90':r['q'][2,h],'daily_gap_prob':r['daily_gap_prob'][h]}
 for r in results for h in range(cfg.horizon)])
flat.to_parquet(out,index=False)
summary.to_csv(out.with_suffix('.summary.csv'),index=False)
meta=dict(protocol='supplemental_unseen_companies',cv=0,flow_scope='business_without_internal_transfers_including_recurring',
 gap_threshold=cfg.gap_threshold,horizon=30,paths=cfg.n_paths,seed=cfg.seed,source_sha256_at_start=source,
 source_changed_during_run=source!=source_fingerprint(),flows_sha256=hashlib.sha256(DEFAULT_FLOWS.read_bytes()).hexdigest(),
 evaluated_companies=sorted(ids),excluded_from_fit=sorted(excluded),training_companies=len(companies)-len(excluded),
 limitation='Additional internal check after main audit; no tuning, no pooling with locked audit; same synthetic source.')
out.with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2))
per=pd.DataFrame(results)
seg=[]
for name,mask in [('actual_short_under_90d',per.history_days<90),('long_history',per.history_days>=90)]:
 for model,g in per[mask].groupby('model'):
  seg.append(dict(segment=name,model=model,**_metrics(g,cfg)))
pd.DataFrame(seg).to_csv(out.with_suffix('.segments.csv'),index=False)
print(summary[summary.companies=='all'][['model','runs','business_path_wape','biz_coverage','gap_precision','gap_recall']].to_string(index=False),flush=True)

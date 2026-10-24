"""Causal company-crossfit residual calibration of saved Chronos point paths.

Research only. For an origin, calibration uses the latest fully observed 30-day
error block from each OTHER-fold company, whose target ends by that origin.
No audit company, future outcome, or same-fold company calibrates that forecast.
The model predicts net flow only; it is not registered in the gRPC service.
"""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from zavozik_ml.data import load_companies,DEFAULT_FLOWS
from zavozik_ml.eval.backtest import Config,stress_history,summarize,_first_day_below
root=Path(__file__).resolve().parents[1]
source=root/'data/chronos_development.parquet'
df=pd.read_parquet(source)
base=pd.read_parquet(root/'data/final_development.parquet')
companies={c.id:c for c in load_companies()}
ids=np.array(sorted(df.company_id.unique()))
np.random.default_rng(20261024).shuffle(ids)
fold={cid:i for i,g in enumerate(np.array_split(ids,3)) for cid in g}
spec=json.loads((root/'eval/split_v1.json').read_text())
assert not set(ids)&set(spec['audit_companies'])
cfg=Config(n_paths=600)
records=[]
for (cid,asof,scenario),g in df.groupby(['company_id','as_of','scenario']):
    g=g.sort_values('h');r=g.iloc[0].to_dict()
    c=companies[cid];o=c.history.dates.index(pd.Timestamp(asof).date())
    hist=stress_history(c.history.head(o+1),scenario)
    valid=~hist.missing[-91:]
    activity=(hist.inflow[-91:]+hist.outflow[-91:])[valid]
    scale=float(activity.mean())+1 if len(activity) else 1.
    r.update(actual=g.actual.to_numpy(),adjusted=g.adjusted.to_numpy(),q=np.array([g.p10,g.p50,g.p90]),
        daily_gap_prob=g.daily_gap_prob.to_numpy(),scale=scale,fold=fold[cid],target_end=pd.Timestamp(asof)+pd.Timedelta(days=30))
    records.append(r)
results=[];diagnostics=[];keys=set()
for scenario in sorted(df.scenario.unique()):
    group=[r for r in records if r['scenario']==scenario]
    for r in group:
        candidates=[p for p in group if p['fold']!=r['fold'] and p['target_end']<=pd.Timestamp(r['as_of'])]
        latest={}
        for p in sorted(candidates,key=lambda p:p['as_of']):latest[p['company_id']]=p
        candidates=list(latest.values())
        if len(candidates)<20:continue
        assert all(p['company_id']!=r['company_id'] and p['target_end']<=pd.Timestamp(r['as_of']) for p in candidates)
        residual=np.array([(p['adjusted']-p['q'][1])/p['scale'] for p in candidates])
        # Keep the original point forecast; calibrate uncertainty around it.
        residual-=np.median(residual,axis=0)
        seed=int.from_bytes(hashlib.sha256(f"42:residual:{r['company_id']}:{r['as_of']}:{scenario}".encode()).digest()[:8],'little')
        rng=np.random.default_rng(seed)
        balance=r['q'][1]+residual[rng.integers(len(residual),size=cfg.n_paths)]*r['scale']
        q=np.quantile(balance,[.1,.5,.9],axis=0)
        pred=_first_day_below(balance,.1)
        result={k:v for k,v in r.items() if k not in ['scale','fold','target_end']}
        result.update(model='chronos_tiny_residual_calibrated',q=q,daily_gap_prob=(balance<0).mean(axis=0),
            gap_prob=float((balance.min(axis=1)<0).mean()),gap_alarm=pred is not None,pred_gap_day=pred,
            pred_shortfall=max(0.,-float(q[1].min())),mae_run=float(np.abs(r['actual']-q[1]).mean()),low_confidence=True)
        results.extend([result,{k:v for k,v in r.items() if k not in ['scale','fold','target_end']}])
        keys.add((r['company_id'],r['as_of'],scenario))
        diagnostics.append(dict(company_id=r['company_id'],as_of=r['as_of'],scenario=scenario,
            calibration_companies=len(candidates),latest_calibration_target=max(p['target_end'] for p in candidates)))
for (model,cid,asof,scenario),g in base[base.model.isin(['auto','seasonal_naive'])].groupby(['model','company_id','as_of','scenario']):
    if (cid,asof,scenario) not in keys:continue
    g=g.sort_values('h');r=g.iloc[0].to_dict()
    r.update(actual=g.actual.to_numpy(),adjusted=g.adjusted.to_numpy(),q=np.array([g.p10,g.p50,g.p90]),daily_gap_prob=g.daily_gap_prob.to_numpy())
    results.append(r)
summary=summarize(results,cfg,set(ids))
out=root/'data/chronos_calibration'
summary.to_csv(out.with_suffix('.summary.csv'),index=False)
pd.DataFrame(diagnostics).to_csv(out.with_suffix('.origins.csv'),index=False)
flat=pd.DataFrame([{k:v for k,v in r.items() if k not in ('actual','adjusted','q','daily_gap_prob')}|
    {'h':h+1,'actual':r['actual'][h],'adjusted':r['adjusted'][h],'p10':r['q'][0,h],'p50':r['q'][1,h],'p90':r['q'][2,h],
     'daily_gap_prob':r['daily_gap_prob'][h]} for r in results for h in range(30)])
flat.to_parquet(out.with_suffix('.parquet'),index=False)
meta={'protocol':'development_only_causal_crossfit_calibration','folds':3,'minimum_calibration_companies':20,
    'calibration_unit':'latest completed 30-day error trajectory per other-fold company',
    'scale':'mean observed inflow+outflow over trailing 91 days of the available scenario history, plus one',
    'preserve_point':'subtract calibration median error at each horizon before resampling',
    'future_information_used':False,'same_fold_calibration_used':False,'serving_model_changed':False,
    'point_predictions_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'flows_sha256':hashlib.sha256(DEFAULT_FLOWS.read_bytes()).hexdigest(),
    'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'limitation':'Internal research on inspected synthetic development data; subset with enough prior calibration companies only. Net-flow target, not gross inflow/outflow.'}
out.with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2))
print(summary[summary.companies=='all'][['scenario','model','runs','business_path_wape','biz_coverage','biz_pinball','gap_precision','gap_recall','gap_brier']].to_string(index=False))

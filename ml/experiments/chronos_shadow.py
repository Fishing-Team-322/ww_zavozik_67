"""Development-only shadow comparison of a pinned Chronos-T5 Tiny.

Chronos predicts signed net cash flow, so the derived positive/negative parts
are valid for balance evaluation but are NOT gross inflow/outflow forecasts.
This experiment does not register a model in the serving process.
"""
from __future__ import annotations

import argparse, hashlib, json, time
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from chronos import ChronosPipeline
from huggingface_hub import hf_hub_download
from zavozik_ml import calendar
from zavozik_ml.data import load_companies, DEFAULT_FLOWS
from zavozik_ml.forecasters.base import Forecaster, Paths
from zavozik_ml.eval.backtest import Config, Origin, evaluate_origin, summarize
from zavozik_ml.provenance import source_fingerprint

ROOT=Path(__file__).resolve().parents[1]
MODEL='amazon/chronos-t5-tiny'
REVISION='29d808298f1a62493e7b9a5e08529d0d930fa189'


class ChronosNet(Forecaster):
    name='chronos_tiny'
    description='Research-only Chronos net-flow trajectories'

    def __init__(self):
        self.pipeline=ChronosPipeline.from_pretrained(MODEL,revision=REVISION,device_map='cpu',
            dtype=torch.float32,trust_remote_code=False,use_safetensors=True,local_files_only=True)

    def forecast(self,history,horizon,n_paths,rng):
        net=(history.inflow-history.outflow).copy()
        net[history.missing]=np.nan
        torch.manual_seed(int(rng.integers(2**31)))
        samples=self.pipeline.predict(torch.tensor(net[-512:],dtype=torch.float32),
            prediction_length=horizon,num_samples=n_paths)[0].numpy().astype(float)
        dates=np.array([history.dates[-1]+timedelta(days=i+1) for i in range(horizon)],dtype='datetime64[D]')
        samples*=calendar.forecast_day_mask(history,dates)
        if not np.isfinite(samples).all():
            raise ValueError('Chronos produced nonfinite paths')
        return Paths(np.maximum(samples,0),np.maximum(-samples,0),low_confidence=history.valid_days<28)


def flat_results(results,cfg):
    return pd.DataFrame([{k:v for k,v in r.items() if k not in ('actual','adjusted','q','daily_gap_prob')}|
        {'h':h+1,'actual':r['actual'][h],'adjusted':r['adjusted'][h],'p10':r['q'][0,h],'p50':r['q'][1,h],
         'p90':r['q'][2,h],'daily_gap_prob':r['daily_gap_prob'][h]} for r in results for h in range(cfg.horizon)])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scenarios',default='standard,short_14,short_28')
    ap.add_argument('--paths',type=int,default=600)
    ap.add_argument('--limit',type=int,default=0,help='smoke only: first N origins')
    ap.add_argument('--out',type=Path,default=ROOT/'data/chronos_development.parquet')
    args=ap.parse_args()
    torch.set_num_threads(4)
    model=ChronosNet()
    companies={c.id:c for c in load_companies()}
    baseline=pd.read_parquet(ROOT/'data/final_development.parquet')
    scenarios=args.scenarios.split(',')
    origins=baseline[['company_id','as_of']].drop_duplicates().sort_values(['company_id','as_of'])
    if args.limit:origins=origins.head(args.limit)
    cfg=Config(n_paths=args.paths,scenarios=tuple(scenarios))
    spec=json.loads((ROOT/'eval/split_v1.json').read_text())
    assert not set(origins.company_id)&set(spec['audit_companies'])
    assert all(str(d)<spec['audit_start'] for d in origins.as_of)
    started=time.monotonic();results=[];latency=[]
    for i,row in enumerate(origins.itertuples(index=False),1):
        c=companies[row.company_id]
        as_of=pd.Timestamp(row.as_of).date()
        org=Origin(c,c.history.dates.index(as_of))
        for scenario in scenarios:
            key=f'{cfg.seed}:{model.name}:{c.id}:{as_of}:{scenario}'
            seed=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'little')
            t=time.monotonic()
            results.append(evaluate_origin(model,org,cfg,np.random.default_rng(seed),scenario))
            latency.append(time.monotonic()-t)
        if i%10==0 or i==1:
            print(f'{i}/{len(origins)} origins; elapsed {time.monotonic()-started:.1f}s; mean request {np.mean(latency):.2f}s',flush=True)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            flat_results(results,cfg).to_parquet(args.out.with_suffix('.checkpoint.parquet'),index=False)
    keys=set(zip(origins.company_id,origins.as_of))
    reference=baseline[(baseline.model=='seasonal_naive')&baseline.scenario.isin(scenarios)]
    refs=[]
    for (cid,asof,scenario),g in reference.groupby(['company_id','as_of','scenario']):
        if (cid,asof) not in keys:continue
        g=g.sort_values('h');r=g.iloc[0].to_dict()
        r.update(actual=g.actual.to_numpy(),adjusted=g.adjusted.to_numpy(),
            q=np.array([g.p10.to_numpy(),g.p50.to_numpy(),g.p90.to_numpy()]),daily_gap_prob=g.daily_gap_prob.to_numpy())
        refs.append(r)
    summary=summarize(results+refs,cfg,set(origins.company_id))
    flat=flat_results(results,cfg)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    flat.to_parquet(args.out,index=False)
    summary.to_csv(args.out.with_suffix('.summary.csv'),index=False)
    weight=Path(hf_hub_download(MODEL,'model.safetensors',revision=REVISION,local_files_only=True))
    meta=dict(protocol='development_only_shadow',model=MODEL,revision=REVISION,license='apache-2.0',
        weights_sha256=hashlib.sha256(weight.read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        source_sha256=source_fingerprint(),flows_sha256=hashlib.sha256(DEFAULT_FLOWS.read_bytes()).hexdigest(),
        paths=cfg.n_paths,scenarios=scenarios,origins=len(origins),fitted_on_case=False,
        target='signed net business flow; not gross inflow/outflow',calendar_mask='history-based existing policy',
        seconds=time.monotonic()-started,p50_request_seconds=float(np.median(latency)),p95_request_seconds=float(np.quantile(latency,.95)))
    args.out.with_suffix('.metadata.json').write_text(json.dumps(meta,indent=2))
    print(summary[summary.companies=='all'][['scenario','model','runs','business_path_wape','biz_coverage','gap_precision','gap_recall','gap_brier']].to_string(index=False),flush=True)

if __name__=='__main__':main()

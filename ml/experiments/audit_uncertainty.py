"""Paired bootstrap by company, preserving dependence of dates within a company."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
df=pd.read_parquet(ROOT/'data/final_audit.parquet')
assert set(df.scenario) == {'standard'}, 'Do not pool stress scenarios with the audit'
keys=['company_id','as_of','h']
baseline=df[df.model=='seasonal_naive'].sort_values(keys)
for model,g in df.groupby('model'):
 g=g.sort_values(keys)
 assert g[keys].reset_index(drop=True).equals(baseline[keys].reset_index(drop=True)), model
 assert np.array_equal(g.adjusted.to_numpy(),baseline.adjusted.to_numpy(),equal_nan=True), model
companies=sorted(df.company_id.unique())
rng=np.random.default_rng(20261024)
weights=rng.multinomial(len(companies),np.full(len(companies),1/len(companies)),size=10000)
rows=[];errors={};denoms={}
for model,g in df.groupby('model'):
 per=g.assign(error=(g.adjusted-g.p50).abs(),denom=g.adjusted.abs()).groupby('company_id')[['error','denom']].sum().reindex(companies)
 errors[model]=per.error.to_numpy();denoms[model]=per.denom.to_numpy()
 draws=(weights@errors[model])/(weights@denoms[model])
 rows.append(dict(model=model,metric='business_path_wape',estimate=per.error.sum()/per.denom.sum(),
                  lower95=float(np.quantile(draws,.025)),upper95=float(np.quantile(draws,.975))))
for model in errors:
 if model=='seasonal_naive':continue
 draws=(weights@(errors['seasonal_naive']-errors[model]))/(weights@denoms[model])
 rows.append(dict(model=model,metric='wape_reduction_vs_naive',estimate=float((errors['seasonal_naive']-errors[model]).sum()/denoms[model].sum()),
                  lower95=float(np.quantile(draws,.025)),upper95=float(np.quantile(draws,.975))))
out=ROOT/'reports/metrics/audit_company_bootstrap.csv'
pd.DataFrame(rows).to_csv(out,index=False)
meta=dict(seed=20261024,replicates=10000,unit='company',companies=len(companies),
 input_sha256=hashlib.sha256((ROOT/'data/final_audit.parquet').read_bytes()).hexdigest(),
 limitation='Internal synthetic audit. Cluster bootstrap is conditional on these companies; it does not model external distribution shift. No recall interval is claimed from nine observed events.')
out.with_suffix('.json').write_text(json.dumps(meta,indent=2))
print(pd.DataFrame(rows).to_string(index=False))

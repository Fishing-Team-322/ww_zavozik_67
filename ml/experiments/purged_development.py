"""Additional time separation: every development target predates audit_start.

The original v1 protocol separated origin dates and company IDs. A 30-day
horizon from a June origin may extend into July. This diagnostic removes those
origins from already causal predictions; no fitting or selection is repeated.
"""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from zavozik_ml.eval.backtest import Config,summarize
root=Path(__file__).resolve().parents[1]
spec=json.loads((root/'eval/split_v1.json').read_text())
source=root/'data/final_development.parquet'
df=pd.read_parquet(source)
original_count=df[['company_id','as_of']].drop_duplicates().shape[0]
df=df[pd.to_datetime(df.as_of)+pd.to_timedelta(df.h.max(),unit='D')<pd.Timestamp(spec['audit_start'])]
assert not set(df.company_id)&set(spec['audit_companies'])
rows=[]
for _,g in df.groupby(['model','company_id','as_of','scenario']):
    g=g.sort_values('h')
    r=g.iloc[0].to_dict()
    r.update(actual=g.actual.to_numpy(),adjusted=g.adjusted.to_numpy(),q=np.array([g.p10,g.p50,g.p90]),daily_gap_prob=g.daily_gap_prob.to_numpy())
    rows.append(r)
out=root/'reports/metrics/purged_development.summary.csv'
summary=summarize(rows,Config(n_paths=600),set(df.company_id))
summary.to_csv(out,index=False)
out.with_name('purged_development.metadata.json').write_text(json.dumps({'protocol':'posthoc_target_disjoint_diagnostic',
    'origin_count_before':original_count,'origin_count_after':df[['company_id','as_of']].drop_duplicates().shape[0],
    'companies':int(df.company_id.nunique()),'last_target_exclusive':spec['audit_start'],
    'source_predictions_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'limitation':'Post-hoc stricter calendar diagnostic. No model changes, no new fit, not a new independent audit.'},indent=2))
print(summary[(summary.companies=='all')&(summary.scenario=='standard')][['model','runs','business_path_wape','biz_coverage','gap_precision','gap_recall']].to_string(index=False))

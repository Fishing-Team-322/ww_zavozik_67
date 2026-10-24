"""Live integration stress check; run against an explicitly started local ML server."""
import argparse
import concurrent.futures as cf
import hashlib,json,time,statistics,grpc,numpy as np
from datetime import date,timedelta
from pathlib import Path
from forecast.v1 import forecaster_pb2 as f, forecaster_pb2_grpc as fg
from categorize.v1 import categorizer_pb2 as c, categorizer_pb2_grpc as cg
from zavozik_ml import calendar
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--address',default='127.0.0.1:50071')
parser.add_argument('--requests',type=int,default=120)
parser.add_argument('--workers',type=int,default=8)
parser.add_argument('--out',type=Path,default=Path('data/concurrency.json'))
args=parser.parse_args()
channel=grpc.insecure_channel(args.address, options=[('grpc.max_receive_message_length',64<<20),('grpc.max_send_message_length',64<<20)])
forecast, classify = fg.ForecasterServiceStub(channel).Forecast, cg.CategorizerServiceStub(channel).Classify
dates=[date(2026,1,1)+timedelta(days=i) for i in range(200)]
history=[f.DailyFlow(date=d.isoformat(),inflow=12000 if calendar.is_workday([d])[0] else 0,outflow=9000 if calendar.is_workday([d])[0] else 0) for d in dates]
reqs=[f.ForecastRequest(model=m,history=history,horizon_days=h,n_paths=200,seed=42,flow_scope='business_without_internal_transfers') for m in ['ensemble','gbm_global','seasonal_naive','ets'] for h in [7,30,90]]
expected={i:forecast(r,timeout=30).SerializeToString(deterministic=True) for i,r in enumerate(reqs)}
def one(i):
 t=time.perf_counter();idx=i%len(reqs)
 result=forecast(reqs[idx],timeout=30).SerializeToString(deterministic=True)
 assert result==expected[idx],f'concurrency changed forecast {idx}'
 return time.perf_counter()-t
with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
 latencies=list(ex.map(one,range(args.requests)))
ops=[c.Operation(id=str(i),direction='out',amount=1000,payment_purpose='Заработная плата за июнь',counterparty_name='ПАО Банк') for i in range(5000)]
r=classify(c.ClassifyRequest(operations=ops),timeout=30)
assert len(r.results)==5000 and all(x.category=='salary' and x.id==str(i) for i,x in enumerate(r.results))
for request,method in [(f.ForecastRequest(model='ensemble',history=history,horizon_days=366,n_paths=5000),forecast),(c.ClassifyRequest(operations=ops+[ops[0]]),classify)]:
 try: method(request,timeout=30);raise AssertionError('oversized request accepted')
 except grpc.RpcError as e: assert e.code()==grpc.StatusCode.INVALID_ARGUMENT
# A cancelled call must not break subsequent successful calls.
future=forecast.future(reqs[-1],timeout=30);future.cancel()
assert forecast(reqs[0],timeout=30).SerializeToString(deterministic=True)==expected[0]
summary={'concurrent_requests':len(latencies),'workers':args.workers,'p50_seconds':statistics.median(latencies),'p95_seconds':float(np.quantile(latencies,.95)),'max_seconds':max(latencies),'classifier_batch':5000,'invalid_limits_rejected':True,'post_cancel_healthy':True,'model_versions':sorted({forecast(r,timeout=30).model_version for r in reqs})}
args.out.parent.mkdir(parents=True,exist_ok=True)
args.out.write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))

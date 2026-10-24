"""Check valid near-limit requests on an explicitly selected test gRPC server."""
import argparse,json,random,time
from datetime import date,timedelta
from pathlib import Path
import grpc
import numpy as np
from categorize.v1 import categorizer_pb2 as c,categorizer_pb2_grpc as cg
from forecast.v1 import forecaster_pb2 as f,forecaster_pb2_grpc as fg
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--address',required=True)
ap.add_argument('--out',type=Path,default=Path('ml/reports/metrics/service_limits.json'))
args=ap.parse_args()
rng=random.Random(20261024)
ops=[]
for i in range(5000):
    # Unique alphabetic suffixes survive number normalization, unlike IDs.
    suffix=' '.join(''.join(rng.choices('абвгдежзиклмнопрстуфхцчшщэюя',k=12)) for _ in range(22))
    ops.append(c.Operation(id=str(i),direction='out',amount=1000,
        payment_purpose='Оплата по договору за услуги. '+suffix,counterparty_name='ООО Тест'))
text_chars=sum(len(o.id)+len(o.payment_purpose)+len(o.counterparty_name) for o in ops)
assert text_chars<2_000_000
channel=grpc.insecure_channel(args.address,options=[('grpc.max_receive_message_length',64<<20),('grpc.max_send_message_length',64<<20)])
classifier=cg.CategorizerServiceStub(channel)
t=time.perf_counter();response=classifier.Classify(c.ClassifyRequest(operations=ops),timeout=60)
classification_seconds=time.perf_counter()-t
assert len(response.results)==len(ops)
assert all(r.id==o.id and np.isfinite(r.confidence) and 0<=r.confidence<=1 for o,r in zip(ops,response.results))
print('5000 distinct operations:',classification_seconds,'seconds',flush=True)
history=[f.DailyFlow(date=(date(2026,1,1)+timedelta(days=i)).isoformat(),inflow=100,outflow=30) for i in range(120)]
request=f.ForecastRequest(model='seasonal_naive',history=history,horizon_days=200,n_paths=5000,seed=42)
forecaster=fg.ForecasterServiceStub(channel)
t=time.perf_counter();paths=forecaster.Forecast(request,timeout=60)
forecast_seconds=time.perf_counter()-t
assert len(paths.paths)==5000 and len(paths.dates)==200
assert all(len(p.inflow)==len(p.outflow)==200 and all(v==100 for v in p.inflow) and all(v==30 for v in p.outflow) for p in paths.paths)
# A large completed call must not prevent the next small call from succeeding.
assert classifier.Classify(c.ClassifyRequest(operations=ops[:1]),timeout=10).results[0].id=='0'
result={'distinct_classification_operations':5000,'text_characters':text_chars,'classification_seconds':classification_seconds,
    'forecast_path_cells':1_000_000,'forecast_seconds':forecast_seconds,'forecast_response_bytes':paths.ByteSize(),
    'classifier_version':response.model_version,'forecast_version':paths.model_version,'healthy_after_large_requests':True,
    'limitation':'Single near-limit smoke on local Docker; not a production throughput or latency SLA.'}
args.out.parent.mkdir(parents=True,exist_ok=True)
args.out.write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2),flush=True)

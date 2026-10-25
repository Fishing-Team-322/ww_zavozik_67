#!/usr/bin/env python3
"""Bounded private Qwen contract/resource probe; never changes running PULS."""
import json,subprocess,time,sys,re
from pathlib import Path
sha=sys.argv[1]
if not re.fullmatch(r'[0-9a-f]{40}',sha):raise SystemExit('full release SHA required')
name='puls-qwen-probe-'+sha[:12];image='ghcr.io/fishing-team-322/puls-qwen:'+sha
meta=json.loads(Path('/opt/puls/qwen-artifact.json').read_text())
model=meta['server_directory']
if model!='/opt/puls/models/qwen/'+meta['release_sha256']:raise SystemExit('invalid reviewed model path')
def run(args,timeout=60):return subprocess.run(args,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout).stdout
report={'candidate':sha,'memory_limit_mib':2048,'cpu_limit':2,'network':'none','tests':'synthetic contract/resource probe, not model accuracy'}
try:
 run(['docker','run','-d','--name',name,'--memory','2g','--memory-swap','2g','--cpus','2','--network','none','--mount','type=bind,src='+model+',dst=/app/qwen-model,readonly','-e','HF_HUB_OFFLINE=1','-e','TRANSFORMERS_OFFLINE=1','-e','QWEN_THREADS=2','-e','QWEN_BATCH_SIZE=1','-e','OMP_NUM_THREADS=1','-e','OPENBLAS_NUM_THREADS=1','-e','TOKENIZERS_PARALLELISM=false',image,'python','-m','zavozik_ml.category_discovery.working_server','--model','/app/qwen-model','--listen','127.0.0.1:50054'])
 stop=time.monotonic()+180
 while True:
  state=json.loads(run(['docker','inspect','--format','{{json .State}}',name]))
  if not state['Running']:raise RuntimeError('probe exited: '+json.dumps(state))
  try:
   run(['docker','exec',name,'python','-m','zavozik_ml.serving.health','--service','qwen','--address','127.0.0.1:50054'],timeout=12);break
  except Exception:
   if time.monotonic()>=stop:raise RuntimeError('Qwen readiness timed out')
   time.sleep(2)
 code='''import json,time,grpc
from categorize.v3 import discovery_pb2 as pb,discovery_pb2_grpc as rpc
texts=['Выплата заработной платы','Арендная плата за помещение','Перевод между своими счетами','Предоставление займа учредителем','Получение банковского кредита','Лизинговый платеж за автомобиль','По договору','Оплата за товар '+('материалы '*350)]
with grpc.insecure_channel('127.0.0.1:50054') as ch:
 s=rpc.DiscoveryServiceStub(ch);t=s.GetTaxonomy(pb.GetTaxonomyRequest(),timeout=10);start=time.perf_counter();r=s.Assign(pb.AssignRequest(operations=[pb.Operation(id='probe-'+str(i),direction='out',payment_purpose=text) for i,text in enumerate(texts)]),timeout=180)
 assert len(r.results)==8 and r.embedding_dim==1024 and r.taxonomy_version==t.taxonomy_version
 assert all(len(a.embedding)==1024 and a.forecast_projection_version for a in r.results)
 print(json.dumps(dict(status='PASS',operations=8,seconds=time.perf_counter()-start,taxonomy_version=t.taxonomy_version,statuses=[a.status for a in r.results])))
'''
 result=run(['docker','exec',name,'python','-c',code],timeout=200);report.update(json.loads(result))
 try:report['peak_memory_mib']=int(run(['docker','exec',name,'cat','/sys/fs/cgroup/memory.peak']))/2**20
 except Exception:report['peak_memory_mib']=None
 report['final_state']=json.loads(run(['docker','inspect','--format','{{json .State}}',name]))
except Exception as e:
 report.update(status='FAIL',error=str(e))
 try:report['logs']=run(['docker','logs','--tail','20',name])
 except Exception:pass
finally:
 Path('/opt/puls/qwen-probe-report.json').write_text(json.dumps(report,indent=2)+'\n')
 subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(json.dumps(report,indent=2))
if report['status']!='PASS':raise SystemExit(1)

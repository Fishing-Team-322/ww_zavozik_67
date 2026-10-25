"""Separate Qwen CPU service; native taxonomy plus explicit M6 output hints."""
import argparse
from concurrent import futures
import json
from pathlib import Path
import threading

import grpc
from categorize.v3 import discovery_pb2 as pb,discovery_pb2_grpc as rpc

from .working_model import WorkingModel
from .forecast_bridge import project_operations,daily_history


class Service(rpc.DiscoveryServiceServicer):
    def __init__(self,model):self.model=model;self.lock=threading.Lock()
    def GetTaxonomy(self,request,context):
        nodes=self.model.nodes
        return pb.GetTaxonomyResponse(categories=[pb.Category(id=n['id'],title=n['title'],
            title_status=n['title_status'],direction=n['direction'],independent_families=n['support']['families'],
            companies=n['support']['companies'],attributes_status='separate_per_operation_forecast_text_evidence',
            parent_id=n['parent_id'] or '',node_kind='group' if n['level']=='coarse' else 'leaf',coarse_level=n['level']=='coarse') for n in nodes],
            encoder_version='qwen3-embedding-0.6b-97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3-1024',
            taxonomy_version=self.model.version,hierarchy_version=self.model.version)
    def Assign(self,request,context):
        if len(request.operations)>64:context.abort(grpc.StatusCode.INVALID_ARGUMENT,'Qwen batch limit64; split large imports')
        if len({o.id for o in request.operations})!=len(request.operations) or any(not o.id or o.direction not in ('in','out') or len(o.id)>256 or len(o.payment_purpose)>8192 for o in request.operations):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,'invalid direction/operation text')
        ops=[dict(id=o.id,direction=o.direction,purpose=o.payment_purpose,counterparty_name=o.counterparty_name) for o in request.operations]
        try:
            with self.lock:results,x=self.model.assign(ops)
        except (ValueError,FloatingPointError) as exc:context.abort(grpc.StatusCode.INVALID_ARGUMENT,str(exc))
        reply=[]
        for r,embedding in zip(results,x):
            fields=dict(id=r['id'],embedding=embedding,category_id=r.get('category_id') or '',
                category_title=r.get('category_title') or '',status=r['status'],category_path=r['category_path'],
                coarse_category_id=r.get('coarse_category_id') or '',coarse_category_title=r.get('coarse_category_title') or '',
                candidates=[pb.Candidate(**c) for c in r['candidates']],channel=r['channel'],tags=r['tags'],
                auxiliary_source=r['auxiliary_source'],forecast_category=r['forecast_category'],
                forecast_projection_version=self.model.document['projection_version'],forecast_projection_source=r['forecast_projection_source'])
            if r.get('similarity') is not None:fields['similarity']=r['similarity']
            reply.append(pb.Assignment(**fields))
        return pb.AssignResponse(results=reply,embedding_dim=1024,taxonomy_version=self.model.version,
            hierarchy_version=self.model.version,encoder_version='qwen3-embedding-0.6b-97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3-1024',
            score_kind='weakly_calibrated_relation_cosine_not_probability')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--listen',default='127.0.0.1:50054');p.add_argument('--input',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--forecast-output',type=Path)
    p.add_argument('--history-coverage',type=Path,help='JSON with first_day,last_day,missing_dates from statement coverage; required for forecast output')
    a=p.parse_args()
    if a.forecast_output and (not a.input or not a.history_coverage):p.error('--forecast-output requires --input and explicit --history-coverage')
    coverage=json.loads(a.history_coverage.read_text()) if a.history_coverage else None
    if coverage is not None and (set(coverage)!={'first_day','last_day','missing_dates'} or not isinstance(coverage['missing_dates'],list)):p.error('coverage requires first_day,last_day,missing_dates')
    model=WorkingModel(a.model)
    if a.input:
        ops=[json.loads(line) for line in a.input.read_text().splitlines() if line.strip()];results,_=model.assign(ops)
        document=dict(taxonomy_version=model.version,embedding_dim=1024,results=results)
        if a.output:a.output.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
        else:print(json.dumps(document,ensure_ascii=False))
        if a.forecast_output:
            projection=json.loads((a.model/'forecast_projection.json').read_text())
            projected=project_operations(ops,results,projection,taxonomy_version=model.version)
            history=daily_history(projected,coverage['first_day'],coverage['last_day'],missing_dates=coverage['missing_dates'])
            a.forecast_output.write_text(json.dumps(dict(model='structural_m6',flow_scope='business_without_internal_transfers',
                history=history,transactions=projected.transactions,warnings=projected.warnings),ensure_ascii=False,indent=2)+'\n')
        return
    server=grpc.server(futures.ThreadPoolExecutor(max_workers=2),options=[('grpc.max_receive_message_length',8*1024*1024)])
    rpc.add_DiscoveryServiceServicer_to_server(Service(model),server)
    port=server.add_insecure_port(a.listen)
    if not port:raise RuntimeError('Qwen service bind failed')
    server.start();print('Qwen native categorizer',model.version,'categories',len(model.nodes),'on',a.listen,flush=True)
    try:server.wait_for_termination()
    except KeyboardInterrupt:server.stop(0).wait()


if __name__=='__main__':main()

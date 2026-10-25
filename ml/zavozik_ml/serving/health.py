"""Bounded internal gRPC readiness probes, without loading neural weights twice."""
import argparse
import grpc


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--service',choices=['forecast','qwen'],required=True)
    p.add_argument('--address',required=True);p.add_argument('--require-model')
    a=p.parse_args()
    with grpc.insecure_channel(a.address) as channel:
        if a.service=='qwen':
            from categorize.v3 import discovery_pb2 as pb,discovery_pb2_grpc as rpc
            response=rpc.DiscoveryServiceStub(channel).GetTaxonomy(pb.GetTaxonomyRequest(),timeout=5)
            if not response.taxonomy_version or not response.categories:raise SystemExit('Qwen taxonomy unavailable')
        else:
            from forecast.v1 import forecaster_pb2 as pb,forecaster_pb2_grpc as rpc
            response=rpc.ForecasterServiceStub(channel).ListModels(pb.ListModelsRequest(),timeout=5)
            if not response.models:raise SystemExit('forecast models unavailable')
            if a.require_model and not any(m.name==a.require_model and m.is_default for m in response.models):raise SystemExit('required default forecast model unavailable')


if __name__=='__main__':main()

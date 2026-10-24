from concurrent import futures

import grpc
import numpy as np
import pytest

from categorize.v3 import discovery_pb2 as pb, discovery_pb2_grpc as rpc
from zavozik_ml.category_discovery.core import CategoryInventory, Settings
from zavozik_ml.category_discovery.server import DiscoveryService


class Encoder:
    version = "offline-test"

    def __call__(self, texts):
        return np.array([[1., 0.] for _ in texts], np.float32).reshape(-1, 2)


@pytest.fixture
def client():
    category = dict(id="auto-new", title="аренда помещения", title_status="auto_extractive", direction="out",
                    independent_families=3, companies=2, attributes_status="unknown_requires_separate_evidence", radius=.1)
    inv = CategoryInventory(dict(settings=Settings().__dict__, categories=[category], encoder_version=Encoder.version, embedding_dim=2),
                            np.array([[1, 0]], np.float32))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    rpc.add_DiscoveryServiceServicer_to_server(DiscoveryService(inv, Encoder()), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    yield rpc.DiscoveryServiceStub(channel)
    channel.close()
    server.stop(0).wait()


def test_dynamic_taxonomy_and_ordered_assignments(client):
    tax = client.GetTaxonomy(pb.GetTaxonomyRequest())
    assert [c.id for c in tax.categories] == ["auto-new"]
    response = client.Assign(pb.AssignRequest(operations=[
        pb.Operation(id="a", direction="out", payment_purpose="Аренда помещения цифровыми рублями"),
        pb.Operation(id="a", direction="in", payment_purpose="Аренда помещения"),
        pb.Operation(id="empty", direction="out")]))
    assert response.taxonomy_version == tax.taxonomy_version
    assert [r.id for r in response.results] == ["a", "a", "empty"]
    assert [r.status for r in response.results] == ["assigned", "no_category", "insufficient_text"]
    assert response.results[0].channel == "digital_ruble"
    assert response.results[0].category_id == "auto-new"
    assert response.results[1].category_id == ""
    assert response.score_kind == "cosine_geometry_not_probability"
    assert not response.results[0].HasField("margin")
    assert len(client.Assign(pb.AssignRequest()).results) == 0


@pytest.mark.parametrize("op", [pb.Operation(direction="bad"), pb.Operation(direction="out", payment_purpose="x"*8193)])
def test_invalid_operation_rejected(client, op):
    with pytest.raises(grpc.RpcError) as err:
        client.Assign(pb.AssignRequest(operations=[op]))
    assert err.value.code() == grpc.StatusCode.INVALID_ARGUMENT

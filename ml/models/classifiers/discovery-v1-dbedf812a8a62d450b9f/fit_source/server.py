"""Separate CPU process for the dynamic taxonomy, without LightGBM imports.

python -m zavozik_ml.category_discovery.server --model /path/to/discovery-release
"""
from __future__ import annotations

import argparse
from concurrent import futures
from pathlib import Path
import threading

import grpc
import numpy as np
from categorize.v3 import discovery_pb2 as pb, discovery_pb2_grpc as rpc

from zavozik_ml.classify_v2.text import Operation
from zavozik_ml.classify_v2.weak_labels import annotate
from .core import CategoryInventory, vectors
from .corpus import embedding_text, semantic_text


class DiscoveryService(rpc.DiscoveryServiceServicer):
    def __init__(self, inventory, encoder):
        if inventory.encoder_version != encoder.version:
            raise ValueError("encoder and inventory versions differ")
        self.inventory, self.encoder = inventory, encoder
        self.lock = threading.Lock()

    def GetTaxonomy(self, request, context):
        return pb.GetTaxonomyResponse(categories=[pb.Category(**{k: c[k] for k in (
            "id", "title", "title_status", "direction", "independent_families", "companies", "attributes_status")})
            for c in self.inventory.categories], encoder_version=self.inventory.encoder_version,
            taxonomy_version=self.inventory.version)

    def Assign(self, request, context):
        ops = request.operations
        if len(ops) > 1024 or sum(len(o.id)+len(o.payment_purpose)+len(o.counterparty_name) for o in ops) > 1_000_000:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "operation batch limit exceeded")
        for o in ops:
            if o.direction not in ("in", "out") or len(o.id) > 256 or len(o.payment_purpose) > 8192 or len(o.counterparty_name) > 1024:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid direction or operation text length")
        rows = [dict(id=o.id, direction=o.direction, semantic_text=semantic_text(o.payment_purpose)) for o in ops]
        try:
            with self.lock:
                x = vectors(self.encoder([embedding_text(o.payment_purpose) for o in ops]), len(ops), self.inventory.document["embedding_dim"])
            assignments = self.inventory.assign(rows, x, self.encoder.version)
            results = []
            for o, a, value in zip(ops, assignments, x):
                aux = annotate(Operation(o.direction, o.payment_purpose, o.counterparty_name))
                fields = dict(id=o.id, embedding=value, category_id=a["category_id"] or "", category_title=a["category_title"] or "",
                              status=a["status"], candidates=[pb.Candidate(**c) for c in a["candidates"]],
                              channel=aux.channel, tags=aux.tags, auxiliary_source=aux.source)
                for name in ("similarity", "margin"):
                    if a[name] is not None:
                        fields[name] = a[name]
                results.append(pb.Assignment(**fields))
        except (ValueError, FloatingPointError):
            context.abort(grpc.StatusCode.INTERNAL, "invalid semantic model output")
        except RuntimeError:
            context.abort(grpc.StatusCode.UNAVAILABLE, "semantic encoder unavailable")
        return pb.AssignResponse(results=results, encoder_version=self.encoder.version,
                                 taxonomy_version=self.inventory.version,
                                 embedding_dim=self.inventory.document["embedding_dim"],
                                 score_kind="cosine_geometry_not_probability")


def main():
    from .encoder import SemanticEncoder
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--listen", default="127.0.0.1:50054")
    a = p.parse_args()
    inventory = CategoryInventory.load(a.model / "inventory")
    encoder = SemanticEncoder(a.model / "encoder", device="cpu")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4), options=[("grpc.max_receive_message_length", 8*1024*1024)])
    rpc.add_DiscoveryServiceServicer_to_server(DiscoveryService(inventory, encoder), server)
    if not server.add_insecure_port(a.listen):
        raise RuntimeError("cannot bind discovery port")
    server.start()
    print(f"Discovery service {inventory.version} on {a.listen}; {len(inventory.categories)} categories", flush=True)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0).wait()


if __name__ == "__main__":
    main()

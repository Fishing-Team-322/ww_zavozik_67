"""Optional v2 gRPC service; importing it needs no neural runtime."""
from __future__ import annotations

import logging
import math
import time

import grpc
from categorize.v2 import categorizer_pb2 as pb
from categorize.v2 import categorizer_pb2_grpc as pb_grpc

from zavozik_ml.classify_v2.model import EncoderClassifier
from zavozik_ml.classify_v2.text import Operation

log = logging.getLogger("zavozik_ml")
MAX_OPERATIONS = 1024
MAX_TEXT_CHARS = 1_000_000


class CategorizerService(pb_grpc.CategorizerServiceServicer):
    def __init__(self, classifier: EncoderClassifier | None):
        self.clf = classifier

    def Classify(self, request, context):
        if self.clf is None:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "v2 classifier artifact is not configured")
        ops = request.operations
        if len(ops) > MAX_OPERATIONS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_OPERATIONS} operations per request")
        if sum(len(o.payment_purpose) + len(o.counterparty_name) + len(o.id) for o in ops) > MAX_TEXT_CHARS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "total operation text exceeds batch limit")
        for o in ops:
            if o.direction not in ("in", "out"):
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "direction must be in or out")
            if not math.isfinite(o.amount) or o.amount < 0 or o.amount > 1e15:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "amount must be finite and in [0, 1e15]")
            if o.counterparty_type not in ("", "org", "person", "none", "bad"):
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid counterparty_type; do not send INN")
            if len(o.id) > 256 or len(o.counterparty_name) > 1024 or len(o.payment_purpose) > 8192:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "operation text exceeds limit")
        inputs = [Operation(o.direction, o.payment_purpose, o.counterparty_name,
                            o.counterparty_type or "none", o.amount, o.id) for o in ops]
        started = time.perf_counter()
        try:
            predicted = self.clf.predict(inputs)
            if len(predicted) != len(inputs):
                raise ValueError("model output count mismatch")
            results = [pb.Classification(
                id=o.id, embedding=p.embedding, category=p.category, category_probs=p.category_probs,
                channel=p.channel, channel_probs=p.channel_probs, tags=p.tags, tag_probs=p.tag_probs,
                attributes=pb.Attributes(**p.attributes), novelty=p.novelty, is_novel=p.is_novel,
                taxonomy_version=p.taxonomy_version, model_version=p.model_version,
            ) for o, p in zip(ops, predicted)]
        except (ValueError, FloatingPointError):
            context.abort(grpc.StatusCode.INTERNAL, "v2 model produced invalid output")
        log.info("classify_v2 n=%d model=%s taxonomy=%s ms=%.0f", len(ops), self.clf.model_version,
                 self.clf.taxonomy.version, (time.perf_counter() - started) * 1000)
        return pb.ClassifyResponse(results=results, model_version=self.clf.model_version,
                                   taxonomy_version=self.clf.taxonomy.version,
                                   embedding_dim=self.clf.config["embedding_dim"])


def register(server: grpc.Server, classifier: EncoderClassifier | None):
    pb_grpc.add_CategorizerServiceServicer_to_server(CategorizerService(classifier), server)

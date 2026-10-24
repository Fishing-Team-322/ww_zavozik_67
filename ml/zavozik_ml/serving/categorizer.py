"""gRPC CategorizerService (proto/categorize/v1/categorizer.proto).

В лог — только размер батча, версия модели и время: назначения, суммы,
названия и ИНН не пишем.
"""

from __future__ import annotations

import logging
import time
import math
import hashlib
from pathlib import Path

import grpc
from categorize.v1 import categorizer_pb2 as pb
from categorize.v1 import categorizer_pb2_grpc as pb_grpc

from zavozik_ml.classify import Classifier, Op

log = logging.getLogger("zavozik_ml")

MAX_OPERATIONS = 5000
MAX_TEXT_CHARS = 2_000_000


def load_classifier(directory: Path) -> Classifier | None:
    try:
        clf = Classifier.load(directory)
        digest = hashlib.sha256()
        for name in ("meta.json", "weights.npz"):
            digest.update((directory / name).read_bytes())
        digest.update(Path(__file__).parents[1].joinpath("classify/text.py").read_bytes())
        clf.meta["loaded_digest"] = digest.hexdigest()[:16]
        return clf
    except (OSError, ValueError, KeyError) as e:
        log.warning("classifier %s not loaded: %s", directory, type(e).__name__)
        return None


def model_version(clf: Classifier) -> str:
    return f"classifier-v{clf.meta.get('version', '?')}-{clf.meta.get('loaded_digest', 'in-memory')}"


class CategorizerService(pb_grpc.CategorizerServiceServicer):
    def __init__(self, classifier: Classifier | None):
        self.clf = classifier

    def Classify(self, request, context):
        if self.clf is None:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "classifier artifact is not loaded")
        n = len(request.operations)
        if n > MAX_OPERATIONS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"at most {MAX_OPERATIONS} operations per request")
        if sum(len(o.payment_purpose)+len(o.counterparty_name)+len(o.counterparty_inn)+len(o.id)
               for o in request.operations) > MAX_TEXT_CHARS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "total operation text exceeds batch limit")
        for op in request.operations:
            if op.direction not in ("in", "out"):
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "direction must be in or out")
            if not math.isfinite(op.amount) or op.amount < 0:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "amount must be finite and nonnegative")
            if len(op.payment_purpose) > 8192 or len(op.counterparty_name) > 1024:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "operation text exceeds limit")
            if len(op.counterparty_inn) > 64 or len(op.id) > 256:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "operation identifier exceeds limit")
        t0 = time.perf_counter()
        ops = [Op(direction=o.direction, purpose=o.payment_purpose, counterparty_name=o.counterparty_name,
                  counterparty_inn=o.counterparty_inn, amount=o.amount) for o in request.operations]
        preds = self.clf.predict(ops)
        version = model_version(self.clf)
        log.info("classify n=%d model=%s ms=%.0f", n, version, (time.perf_counter() - t0) * 1000)
        return pb.ClassifyResponse(
            results=[pb.Classification(id=o.id, category=p.category, confidence=p.confidence)
                     for o, p in zip(request.operations, preds)],
            model_version=version,
        )


def register(server: grpc.Server, classifier: Classifier | None) -> None:
    pb_grpc.add_CategorizerServiceServicer_to_server(CategorizerService(classifier), server)

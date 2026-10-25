"""gRPC-сервер ForecasterService (proto/forecast/v1/forecaster.proto).

Без состояния: вся история приходит в запросе. В лог пишем только
company_id, модель и размеры — суммы и даты не пишем.

    PYTHONPATH=gen python -m zavozik_ml.serving.server
"""

from __future__ import annotations

import logging
import hashlib
import os
import signal
from pathlib import Path
from concurrent import futures
from datetime import date, timedelta

import grpc
import numpy as np
from forecast.v1 import forecaster_pb2 as pb
from forecast.v1 import forecaster_pb2_grpc as pb_grpc

from zavozik_ml import forecasters
from zavozik_ml.forecasters.base import domain_warnings, select_model
from zavozik_ml import calendar as cal
from zavozik_ml.forecasters import models  # noqa: F401 — регистрирует все модели
from zavozik_ml.serving import categorizer, categorizer_v2
from zavozik_ml.provenance import source_fingerprint
from zavozik_ml.classify.text import CATEGORIES

log = logging.getLogger("zavozik_ml")

MAX_HORIZON = 366
MAX_PATHS = 5000
MAX_HISTORY = 3650
MAX_CELLS = 1_000_000
MAX_FLOW = 1e15
FLOW_SCOPE = "business_without_internal_transfers"
VERSIONS: dict[str, str] = {}
SOURCE_VERSION = source_fingerprint()[:12]


def to_history(req: pb.ForecastRequest) -> forecasters.History:
    h = req.history
    if not h or len(h) > MAX_HISTORY:
        raise ValueError(f"history must contain 1..{MAX_HISTORY} days")
    values = np.array([(f.inflow, f.outflow) for f in h])
    if not np.isfinite(values).all() or (values < 0).any() or (values > MAX_FLOW).any():
        raise ValueError(f"flows must be finite and in [0, {MAX_FLOW:g}]; use missing for unavailable data")
    if any(k not in CATEGORIES for f in h for k in f.by_category):
        raise ValueError("unknown category in history")
    if any(not np.isfinite(v) or abs(v) > MAX_FLOW for f in h for v in f.by_category.values()):
        raise ValueError(f"category flows must be finite and within +/-{MAX_FLOW:g}")
    dates=[date.fromisoformat(f.date) for f in h]
    seen=set()
    if len(req.transactions)>100000:raise ValueError("too many transactions")
    days={f.date:f for f in h}
    for t in req.transactions:
        if not t.id or t.id in seen or len(t.id)>256:raise ValueError("unique bounded transaction IDs required")
        seen.add(t.id)
        if t.date not in days or days[t.date].missing:raise ValueError("transaction outside observed daily history")
        if t.direction not in ("in","out") or t.category not in CATEGORIES:raise ValueError("invalid transaction direction/category")
        if not np.isfinite(t.amount) or not 0<=t.amount<=MAX_FLOW:raise ValueError("invalid transaction amount")
        if len(t.purpose)>8192 or len(t.counterparty_id)>256:raise ValueError("transaction text exceeds contract limits")
    return forecasters.History(
        dates=dates,
        inflow=values[:, 0],
        outflow=values[:, 1],
        missing=np.fromiter((f.missing for f in h), dtype=bool, count=len(h)),
        industry=req.industry,
        categories=categories_from(h),
        transactions=tuple(
            {"id": t.id, "date": t.date, "amount": t.amount, "direction": t.direction, "category": t.category,
             "counterparty_id": t.counterparty_id, "purpose": t.purpose}
            for t in req.transactions
        ),
    )


def categories_from(h) -> dict[str, np.ndarray]:
    names = sorted({k for f in h for k in f.by_category})
    return {
        c: np.nan_to_num(np.fromiter((f.by_category.get(c, 0.0) for f in h), dtype=float, count=len(h)))
        for c in names
    }


def net_quantiles(dates: list[str], paths: forecasters.Paths) -> list[pb.NetQuantiles]:
    net = paths.inflow - paths.outflow
    q = np.quantile(net, [0.1, 0.5, 0.9], axis=0)
    return [pb.NetQuantiles(date=d, p10=q[0, i], p50=q[1, i], p90=q[2, i]) for i, d in enumerate(dates)]


class ForecasterService(pb_grpc.ForecasterServiceServicer):
    def ListModels(self, request, context):
        default = os.environ.get("ML_DEFAULT_MODEL") or forecasters.default_model()
        return pb.ListModelsResponse(
            models=[
                pb.ModelInfo(name=m.name, description=m.description, is_default=m.name == default)
                for m in forecasters.all_models()
                if m.ready
            ]
        )

    def Forecast(self, request, context):
        if not 0 < request.horizon_days <= MAX_HORIZON:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"horizon_days must be in 1..{MAX_HORIZON}")
        if not 0 < request.n_paths <= MAX_PATHS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"n_paths must be in 1..{MAX_PATHS}")
        if request.n_paths * request.horizon_days > MAX_CELLS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "requested path matrix is too large")
        if request.seed < 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "seed must be nonnegative")
        if request.flow_scope not in ("", FLOW_SCOPE):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "unsupported flow_scope")
        try:
            history = to_history(request)
            requested_model = os.environ.get("ML_DEFAULT_MODEL", "auto") if request.model in ("", "auto") else request.model
            model = select_model(requested_model, history)
            if any((b - a).days != 1 for a, b in zip(history.dates, history.dates[1:])):
                raise ValueError("history must contain consecutive calendar days")
            if (date.max - history.dates[-1]).days < request.horizon_days:
                raise ValueError("forecast dates exceed supported date range")
        except (KeyError, ValueError) as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))
        if history.valid_days == 0:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "history contains no observed days")
        if history.missing[-56:].all():
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "history contains no observed days in the last 8 weeks")

        rng = np.random.default_rng(request.seed or None)
        try:
            paths = model.forecast(history, request.horizon_days, request.n_paths, rng)
        except (forecasters.NotTrainedError, forecasters.InsufficientHistoryError) as e:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))
        if (paths.inflow.shape != (request.n_paths, request.horizon_days)
                or paths.outflow.shape != paths.inflow.shape
                or not np.isfinite(paths.inflow).all() or not np.isfinite(paths.outflow).all()
                or (paths.inflow < 0).any() or (paths.outflow < 0).any()):
            context.abort(grpc.StatusCode.INTERNAL, "model produced invalid paths")

        warnings = list(dict.fromkeys(domain_warnings(history) + list(paths.warnings)))
        if history.valid_days < 28:
            warnings.append("insufficient_history")
        if history.missing.any():
            warnings.append("incomplete_history")
        if request.horizon_days > 30 and model.name in ("gbm_global", "ensemble"):
            warnings.append("naive_tail_after_30_days")
        fallback = model.name in ("gbm_global", "ensemble") and len(history) < 14
        if fallback:
            warnings.append("short_history_naive_fallback")
        elif model.name in ("gbm_global", "ensemble") and len(history) < 56:
            warnings.append("short_history_global_level")
        if request.model in ("", "auto") and model.name == "seasonal_naive":
            fallback = True
            warnings.append("out_of_domain_naive_fallback" if domain_warnings(history) else "global_model_unavailable")

        last = history.dates[-1] if history.dates else date.today()
        dates = [(last + timedelta(days=d + 1)).isoformat() for d in range(request.horizon_days)]
        known_years = {int(p.stem.removeprefix("ru_")) for p in cal.DATA.glob("ru_*.json")}
        if cal.uses_workday_calendar(history) and any(int(d[:4]) not in known_years for d in dates):
            warnings.append("calendar_year_unavailable")
        log.info(
            "forecast company_id=%s model=%s history_days=%d horizon=%d paths=%d low_confidence=%s",
            request.company_id, model.name, len(history.dates), request.horizon_days, request.n_paths,
            paths.low_confidence,
        )
        return pb.ForecastResponse(
            model_used=model.name,
            dates=dates,
            paths=[pb.Path(inflow=paths.inflow[i], outflow=paths.outflow[i]) for i in range(request.n_paths)],
            net_quantiles=net_quantiles(dates, paths),
            low_confidence=paths.low_confidence or any(w in warnings for w in ("nonworkday_activity_detected", "single_channel_history", "calendar_year_unavailable")),
            model_version=model_version(model.name),
            flow_scope=FLOW_SCOPE,
            warnings=warnings,
            fallback_used=fallback,
        )


DEFAULT_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"


def model_version(name: str) -> str:
    if name == "ensemble":
        return f"ensemble-50-50:{model_version('gbm_global')}:{model_version('seasonal_naive')}"
    return f"{VERSIONS.get(name, name)}:code-{SOURCE_VERSION}:release-{os.environ.get("ML_RELEASE_REVISION", "local")}"


def load_artifacts(directory: Path) -> list[str]:
    """Загружает обученные глобальные модели; возвращает имена загруженных."""
    loaded = []
    for m in forecasters.all_models():
        if m.is_global and m.load(directory / m.name):
            loaded.append(m.name)
            digest = hashlib.sha256()
            for f in sorted((directory / m.name).glob("*")):
                if f.is_file():
                    digest.update(f.name.encode())
                    digest.update(f.read_bytes())
            VERSIONS[m.name] = f"{m.name}:{digest.hexdigest()[:16]}"
    return loaded


def build_server(addr: str, workers: int = 8, classifier=None, classifier_v2=None) -> tuple[grpc.Server, int]:
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=workers),
        options=[("grpc.max_receive_message_length", 64 << 20), ("grpc.max_send_message_length", 64 << 20)],
    )
    pb_grpc.add_ForecasterServiceServicer_to_server(ForecasterService(), server)
    categorizer.register(server, classifier)
    categorizer_v2.register(server, classifier_v2)
    port = server.add_insecure_port(addr)
    return server, port


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
    addr = os.environ.get("ML_LISTEN", "0.0.0.0:50051")
    artifacts = Path(os.environ.get("ML_ARTIFACTS", DEFAULT_ARTIFACTS))
    loaded = load_artifacts(artifacts)
    log.info("artifacts %s: loaded %s", artifacts, loaded or "none")
    clf = categorizer.load_classifier(artifacts / "classifier")
    log.info("classifier: %s", categorizer.model_version(clf) if clf else "none")
    clf_v2 = None
    if path_v2 := os.environ.get("ML_CLASSIFIER_V2"):
        # Explicit configuration must fail startup on invalid/missing weights;
        # do not silently serve another model with a different contract.
        from zavozik_ml.classify_v2.model import EncoderClassifier
        import json
        config_v2 = json.loads((Path(path_v2) / "config.json").read_text())
        backend_v2 = os.environ.get("ML_CLASSIFIER_V2_BACKEND") or config_v2.get("runtime", "onnx")
        if backend_v2 == "torch":
            from zavozik_ml.serving.torch_process import load_isolated_classifier
            clf_v2 = load_isolated_classifier(Path(path_v2))
        else:
            clf_v2 = EncoderClassifier.load(Path(path_v2), backend=backend_v2)
        log.info("classifier_v2: %s taxonomy=%s", clf_v2.model_version, clf_v2.taxonomy.version)
    server, _ = build_server(addr, classifier=clf, classifier_v2=clf_v2)
    server.start()
    log.info("ml listening on %s, ready models: %s, auto=%s", addr,
             [m.name for m in forecasters.all_models() if m.ready], forecasters.default_model())
    signal.signal(signal.SIGTERM, lambda *_: server.stop(5))
    try:
        server.wait_for_termination()
    finally:
        if clf_v2 is not None and hasattr(clf_v2.encode, "close"):
            clf_v2.encode.close()


if __name__ == "__main__":
    main()

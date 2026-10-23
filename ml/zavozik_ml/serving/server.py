"""gRPC-сервер ForecasterService (proto/forecast/v1/forecaster.proto).

Без состояния: вся история приходит в запросе. В лог пишем только
company_id, модель и размеры — суммы и даты не пишем.

    PYTHONPATH=gen python -m zavozik_ml.serving.server
"""

from __future__ import annotations

import logging
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
from zavozik_ml.forecasters import models  # noqa: F401 — регистрирует все модели

log = logging.getLogger("zavozik_ml")

MAX_HORIZON = 366
MAX_PATHS = 5000


def to_history(req: pb.ForecastRequest) -> forecasters.History:
    h = req.history
    return forecasters.History(
        dates=[date.fromisoformat(f.date) for f in h],
        inflow=_clean(np.fromiter((f.inflow for f in h), dtype=float, count=len(h))),
        outflow=_clean(np.fromiter((f.outflow for f in h), dtype=float, count=len(h))),
        missing=np.fromiter((f.missing for f in h), dtype=bool, count=len(h)),
        industry=req.industry,
        categories=categories_from(h),
    )


def _clean(x: np.ndarray) -> np.ndarray:
    """Потоки из чужих выгрузок: NaN/inf → 0, отрицательные → модуль."""
    return np.abs(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0))


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
        default = forecasters.default_model()
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
        try:
            model = forecasters.get(request.model)
            history = to_history(request)
            if any((b - a).days != 1 for a, b in zip(history.dates, history.dates[1:])):
                raise ValueError("history must contain consecutive calendar days")
        except (KeyError, ValueError) as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

        rng = np.random.default_rng(request.seed or None)
        try:
            paths = model.forecast(history, request.horizon_days, request.n_paths, rng)
        except forecasters.NotTrainedError as e:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(e))

        last = history.dates[-1] if history.dates else date.today()
        dates = [(last + timedelta(days=d + 1)).isoformat() for d in range(request.horizon_days)]
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
            low_confidence=paths.low_confidence,
        )


DEFAULT_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"


def load_artifacts(directory: Path) -> list[str]:
    """Загружает обученные глобальные модели; возвращает имена загруженных."""
    loaded = []
    for m in forecasters.all_models():
        if m.is_global and m.load(directory / m.name):
            loaded.append(m.name)
    return loaded


def build_server(addr: str, workers: int = 8) -> tuple[grpc.Server, int]:
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=workers),
        options=[("grpc.max_receive_message_length", 64 << 20), ("grpc.max_send_message_length", 64 << 20)],
    )
    pb_grpc.add_ForecasterServiceServicer_to_server(ForecasterService(), server)
    port = server.add_insecure_port(addr)
    return server, port


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
    addr = os.environ.get("ML_LISTEN", "0.0.0.0:50051")
    artifacts = Path(os.environ.get("ML_ARTIFACTS", DEFAULT_ARTIFACTS))
    loaded = load_artifacts(artifacts)
    log.info("artifacts %s: loaded %s", artifacts, loaded or "none")
    server, _ = build_server(addr)
    server.start()
    log.info("ml listening on %s, ready models: %s, auto=%s", addr,
             [m.name for m in forecasters.all_models() if m.ready], forecasters.default_model())
    signal.signal(signal.SIGTERM, lambda *_: server.stop(5))
    server.wait_for_termination()


if __name__ == "__main__":
    main()

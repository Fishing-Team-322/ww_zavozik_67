"""gRPC-сервер ForecasterService (proto/forecast/v1/forecaster.proto).

Без состояния: вся история приходит в запросе. В лог пишем только
company_id, модель и размеры — суммы и даты не пишем.

    PYTHONPATH=gen python -m zavozik_ml.serving.server
"""

from __future__ import annotations

import logging
import os
import signal
from concurrent import futures
from datetime import date, timedelta

import grpc
import numpy as np
from forecast.v1 import forecaster_pb2 as pb
from forecast.v1 import forecaster_pb2_grpc as pb_grpc

from zavozik_ml import forecasters

log = logging.getLogger("zavozik_ml")

MAX_HORIZON = 366
MAX_PATHS = 5000


def to_history(req: pb.ForecastRequest) -> forecasters.History:
    h = req.history
    return forecasters.History(
        dates=[date.fromisoformat(f.date) for f in h],
        inflow=np.fromiter((f.inflow for f in h), dtype=float, count=len(h)),
        outflow=np.fromiter((f.outflow for f in h), dtype=float, count=len(h)),
        missing=np.fromiter((f.missing for f in h), dtype=bool, count=len(h)),
        industry=req.industry,
    )


def net_quantiles(dates: list[str], paths: forecasters.Paths) -> list[pb.NetQuantiles]:
    net = paths.inflow - paths.outflow
    q = np.quantile(net, [0.1, 0.5, 0.9], axis=0)
    return [pb.NetQuantiles(date=d, p10=q[0, i], p50=q[1, i], p90=q[2, i]) for i, d in enumerate(dates)]


class ForecasterService(pb_grpc.ForecasterServiceServicer):
    def ListModels(self, request, context):
        return pb.ListModelsResponse(
            models=[
                pb.ModelInfo(name=m.name, description=m.description, is_default=m.name == forecasters.DEFAULT_MODEL)
                for m in forecasters.all_models()
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
        except (KeyError, ValueError) as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

        rng = np.random.default_rng(request.seed or None)
        paths = model.forecast(history, request.horizon_days, request.n_paths, rng)

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
    server, _ = build_server(addr)
    server.start()
    log.info("ml listening on %s, models: %s", addr, [m.name for m in forecasters.all_models()])
    signal.signal(signal.SIGTERM, lambda *_: server.stop(5))
    server.wait_for_termination()


if __name__ == "__main__":
    main()

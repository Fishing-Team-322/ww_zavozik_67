from datetime import date, timedelta

import grpc
import pytest
from forecast.v1 import forecaster_pb2 as pb
from forecast.v1 import forecaster_pb2_grpc as pb_grpc

from zavozik_ml.serving.server import build_server


@pytest.fixture(scope="module")
def stub():
    server, port = build_server("127.0.0.1:0", workers=2)
    server.start()
    with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
        yield pb_grpc.ForecasterServiceStub(ch)
    server.stop(0)


def test_list_models(stub):
    models = stub.ListModels(pb.ListModelsRequest()).models
    assert any(m.name == "seasonal_naive" and m.is_default for m in models)


def test_forecast(stub):
    start = date(2025, 1, 1)
    history = [pb.DailyFlow(date=(start + timedelta(days=i)).isoformat(), inflow=100, outflow=40) for i in range(60)]
    resp = stub.Forecast(pb.ForecastRequest(model="auto", history=history, horizon_days=30, n_paths=50, seed=7))
    assert resp.model_used == "seasonal_naive"
    assert len(resp.dates) == 30 and resp.dates[0] == "2025-03-02"
    assert len(resp.paths) == 50 and len(resp.paths[0].inflow) == 30
    assert resp.net_quantiles[0].p50 == pytest.approx(60)


def test_forecast_validates(stub):
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(model="nope", horizon_days=30, n_paths=10))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(horizon_days=0, n_paths=10))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT

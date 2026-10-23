from datetime import date, timedelta

import grpc
import pytest
from forecast.v1 import forecaster_pb2 as pb
from forecast.v1 import forecaster_pb2_grpc as pb_grpc

from zavozik_ml import forecasters
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
    assert [m.name for m in models if m.is_default] == [forecasters.default_model()]
    assert any(m.name == "seasonal_naive" for m in models)


def test_forecast(stub):
    start = date(2025, 1, 1)
    history = [pb.DailyFlow(date=(start + timedelta(days=i)).isoformat(), inflow=100, outflow=40) for i in range(60)]
    resp = stub.Forecast(pb.ForecastRequest(model="seasonal_naive", history=history, horizon_days=30, n_paths=50, seed=7))
    assert resp.model_used == "seasonal_naive"
    assert len(resp.dates) == 30 and resp.dates[0] == "2025-03-02"
    assert len(resp.paths) == 50 and len(resp.paths[0].inflow) == 30
    assert resp.net_quantiles[0].p50 == 0  # 2 марта 2025 — воскресенье, операций нет
    assert resp.net_quantiles[1].p50 == pytest.approx(60)  # понедельник


def test_forecast_validates(stub):
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(model="nope", horizon_days=30, n_paths=10))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(horizon_days=0, n_paths=10))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_forecast_rejects_gaps_in_dates(stub):
    history = [pb.DailyFlow(date="2025-01-01"), pb.DailyFlow(date="2025-01-03")]
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(history=history, horizon_days=7, n_paths=5))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_forecast_cleans_bad_values(stub):
    history = [pb.DailyFlow(date=(date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                            inflow=float("nan") if i % 5 == 0 else 100.0, outflow=-40.0) for i in range(60)]
    resp = stub.Forecast(pb.ForecastRequest(model="seasonal_naive", history=history, horizon_days=10, n_paths=20, seed=1))
    assert all(v >= 0 for p in resp.paths for v in list(p.inflow) + list(p.outflow))

from datetime import date, timedelta

import grpc
import pytest
from forecast.v1 import forecaster_pb2 as pb
from forecast.v1 import forecaster_pb2_grpc as pb_grpc

from zavozik_ml import forecasters
from zavozik_ml import calendar as cal
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
    history = [pb.DailyFlow(date=(start + timedelta(days=i)).isoformat(),
                           inflow=100 if cal.is_workday([start + timedelta(days=i)])[0] else 0,
                           outflow=40 if cal.is_workday([start + timedelta(days=i)])[0] else 0) for i in range(60)]
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


def test_forecast_rejects_bad_values_instead_of_inventing_cash(stub):
    history = [pb.DailyFlow(date=(date(2025, 1, 1) + timedelta(days=i)).isoformat(),
                            inflow=float("nan") if i % 5 == 0 else 100.0, outflow=-40.0) for i in range(60)]
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(model="seasonal_naive", history=history, horizon_days=10, n_paths=20, seed=1))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.parametrize("change", [dict(seed=-1), dict(flow_scope="residual_only"), dict(n_paths=5000, horizon_days=366)])
def test_forecast_rejects_invalid_contract(stub, change):
    args = dict(model="seasonal_naive", history=[pb.DailyFlow(date="2026-01-01")], horizon_days=30, n_paths=10)
    args.update(change)
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(**args))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_forecast_has_scope_version_and_reproducible_seed(stub):
    req = pb.ForecastRequest(model="seasonal_naive", history=[pb.DailyFlow(date="2026-01-01", inflow=100)],
                             horizon_days=7, n_paths=20, seed=17)
    a, b = stub.Forecast(req), stub.Forecast(req)
    assert a == b
    assert a.model_version and a.flow_scope == "business_without_internal_transfers"
    assert "insufficient_history" in a.warnings


def test_empty_history_requires_explicit_data(stub):
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(horizon_days=30, n_paths=10))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_all_missing_history_cannot_invent_forecast(stub):
    req = pb.ForecastRequest(model='seasonal_naive', history=[pb.DailyFlow(date='2026-01-01', missing=True)],
                             horizon_days=7, n_paths=10)
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(req)
    assert e.value.code() == grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.parametrize('model', ['seasonal_naive', 'auto', 'gbm_global', 'ensemble', 'ets'])
def test_stale_history_is_failed_precondition_for_every_model(stub, model):
    history = [pb.DailyFlow(date=(date(2026, 1, 1)+timedelta(days=i)).isoformat(),
                           inflow=100, outflow=70, missing=i >= 14) for i in range(70)]
    with pytest.raises(grpc.RpcError) as error:
        stub.Forecast(pb.ForecastRequest(model=model, history=history, horizon_days=30, n_paths=10))
    assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert 'last 8 weeks' in error.value.details()


def test_no_eligible_sampling_days_is_failed_precondition(stub):
    with pytest.raises(grpc.RpcError) as error:
        stub.Forecast(pb.ForecastRequest(model='seasonal_naive',
            history=[pb.DailyFlow(date='2026-03-01')], horizon_days=7, n_paths=10))
    assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION


def test_date_overflow_is_input_error(stub):
    req = pb.ForecastRequest(model='seasonal_naive', history=[pb.DailyFlow(date='9999-12-31')],
                             horizon_days=7, n_paths=10)
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(req)
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_auto_reports_out_of_domain_fallback(stub):
    dates = [date(2026, 1, 1)+timedelta(days=i) for i in range(90)]
    req = pb.ForecastRequest(model='auto', history=[pb.DailyFlow(date=d.isoformat(), outflow=30) for d in dates],
                             horizon_days=30, n_paths=20, seed=7)
    response = stub.Forecast(req)
    assert response.model_used == 'seasonal_naive'
    assert response.fallback_used and response.low_confidence
    assert 'out_of_domain_naive_fallback' in response.warnings
    assert all(all(v==0 for v in path.inflow) for path in response.paths)


@pytest.mark.parametrize('flow', [
    pb.DailyFlow(date='2026-01-01', by_category={'unknown_category': 1}),
    pb.DailyFlow(date='2026-01-01', inflow=1e308),
    pb.DailyFlow(date='2026-01-01', by_category={'salary': -1e308}),
])
def test_forecast_bounds_input_feature_space(stub, flow):
    with pytest.raises(grpc.RpcError) as e:
        stub.Forecast(pb.ForecastRequest(model='seasonal_naive', history=[flow], horizon_days=7, n_paths=10))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT

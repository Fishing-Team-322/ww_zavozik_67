from datetime import date, timedelta

import grpc
import numpy as np
import pytest
from forecast.v1 import forecaster_pb2 as pb
from forecast.v1 import forecaster_pb2_grpc as pb_grpc

from zavozik_ml import forecasters
from zavozik_ml.forecasters import models  # noqa: F401
from zavozik_ml.serving.server import build_server

pytest.importorskip("cashradar.embed", reason="cashradar is not installed (pip install ml/vendor/cashradar-*.whl)")

START = date(2025, 1, 1)


def company(days: int = 240) -> tuple[forecasters.History, list[dict]]:
    """Выручка по будням, зарплата 10-го, аренда 5-го, ЕНП 28-го; счёт клиенту оплачивается через 20 дней."""
    rng = np.random.default_rng(3)
    dates = [START + timedelta(days=i) for i in range(days)]
    wk = np.array([d.weekday() < 5 for d in dates])
    revenue = np.where(wk, rng.gamma(4, 25_000, days), 0.0)
    salary = np.array([300_000.0 if d.day == 10 else 0.0 for d in dates])
    rent = np.array([80_000.0 if d.day == 5 else 0.0 for d in dates])
    tax = np.array([60_000.0 if d.day == 28 else 0.0 for d in dates])
    tx = []
    for i, d in enumerate(dates):
        for amount, direction, cat, cp, purpose in (
            (revenue[i], "in", "revenue_acquiring", "bank", "Зачисление средств по операциям эквайринга"),
            (salary[i], "out", "salary", "bank", "Перечисление заработной платы (окончательный расчет)"),
            (rent[i], "out", "rent", "0011111111", "Оплата аренды нежилого помещения по договору № 1/2"),
            (tax[i], "out", "tax", "fns", "Единый налоговый платеж"),
        ):
            if amount:
                tx.append(dict(id=f"{i}-{cat}", date=d.isoformat(), amount=float(amount), direction=direction,
                               category=cat, counterparty_id=cp, purpose=purpose))
    h = forecasters.History(
        dates=dates, inflow=revenue, outflow=salary + rent + tax, missing=np.zeros(days, dtype=bool),
        industry="Общепит", categories={"revenue_acquiring": revenue, "salary": -salary, "rent": -rent, "tax": -tax},
        transactions=tuple(tx),
    )
    return h, tx


def test_registered_and_ready():
    m = forecasters.get("structural_m6")
    assert m.ready


@pytest.mark.parametrize("with_transactions", [True, False])
def test_paths_contract_and_calendar(with_transactions):
    h, _ = company()
    if not with_transactions:
        h = forecasters.History(h.dates, h.inflow, h.outflow, h.missing, h.industry, h.categories)
    p = forecasters.get("structural_m6").forecast(h, 30, 300, np.random.default_rng(0))
    assert p.inflow.shape == p.outflow.shape == (300, 30)
    assert np.isfinite(p.inflow).all() and (p.inflow >= 0).all() and (p.outflow >= 0).all()
    days = [h.dates[-1] + timedelta(days=i + 1) for i in range(30)]
    salary_day = next(i for i, d in enumerate(days) if d.day == 10 or (d.day in (11, 12) and d.weekday() == 0))
    assert p.outflow[:, salary_day].mean() > 200_000


def test_head_does_not_leak_future_transactions():
    h, _ = company()
    cut = h.head(100)
    assert cut.transactions and max(t["date"] for t in cut.transactions) <= cut.dates[-1].isoformat()


def test_grpc_forecast_with_transactions():
    h, tx = company()
    server, port = build_server("127.0.0.1:0", workers=2)
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
            stub = pb_grpc.ForecasterServiceStub(ch)
            history = [pb.DailyFlow(date=d.isoformat(), inflow=float(i_), outflow=float(o_))
                       for d, i_, o_ in zip(h.dates, h.inflow, h.outflow)]
            txs = [pb.HistoryTransaction(id=t["id"], date=t["date"], amount=t["amount"], direction=t["direction"],
                                         category=t["category"], counterparty_id=t["counterparty_id"],
                                         purpose=t["purpose"]) for t in tx]
            resp = stub.Forecast(pb.ForecastRequest(model="structural_m6", history=history, transactions=txs,
                                                    horizon_days=30, n_paths=100, seed=7))
            assert resp.model_used == "structural_m6" and len(resp.paths) == 100 and len(resp.dates) == 30
    finally:
        server.stop(0)


def test_production_default_and_vendor_warnings_survive_rpc(monkeypatch):
    monkeypatch.setenv("ML_DEFAULT_MODEL","structural_m6")
    monkeypatch.setenv("ML_REQUIRE_M6_GBM","true")
    h,_=company(70)
    server,port=build_server("127.0.0.1:0",workers=2);server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub=pb_grpc.ForecasterServiceStub(channel)
            models=stub.ListModels(pb.ListModelsRequest())
            assert any(m.name=="structural_m6" and m.is_default for m in models.models)
            rows=[pb.DailyFlow(date=d.isoformat(),inflow=float(i),outflow=float(o)) for d,i,o in zip(h.dates,h.inflow,h.outflow)]
            response=stub.Forecast(pb.ForecastRequest(model="auto",history=rows,horizon_days=7,n_paths=12,seed=3))
            assert response.model_used=="structural_m6"
            assert "lite_mode_no_purposes" in response.warnings
            bad=pb.HistoryTransaction(id="outside",date="2030-01-01",amount=1,direction="out",category="other")
            with pytest.raises(grpc.RpcError) as error:
                stub.Forecast(pb.ForecastRequest(model="auto",history=rows,transactions=[bad],horizon_days=7,n_paths=12))
            assert error.value.code()==grpc.StatusCode.INVALID_ARGUMENT
    finally:server.stop(0).wait()

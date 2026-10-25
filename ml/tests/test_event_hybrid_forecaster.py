from datetime import date, timedelta

import grpc
import numpy as np
import pytest
from forecast.v1 import forecaster_pb2 as pb
from forecast.v1 import forecaster_pb2_grpc as pb_grpc

from zavozik_ml import forecasters
from zavozik_ml.forecasters import models  # noqa: F401
from zavozik_ml.forecasters.event_hybrid import event_history
from zavozik_ml.serving.server import build_server

START = date(2025, 1, 1)


def company(days: int = 240) -> forecasters.History:
    """Выручка по будням, зарплата 10-го, аренда 5-го; плюс перевод владельца, которого нет в дневных потоках."""
    rng = np.random.default_rng(3)
    dates = [START + timedelta(days=i) for i in range(days)]
    wk = np.array([d.weekday() < 5 for d in dates])
    revenue = np.where(wk, rng.gamma(4, 25_000, days), 0.0)
    salary = np.array([300_000.0 if d.day == 10 else 0.0 for d in dates])
    rent = np.array([80_000.0 if d.day == 5 else 0.0 for d in dates])
    tx = []
    for i, d in enumerate(dates):
        for amount, direction, cat, cp in ((revenue[i], "in", "revenue_acquiring", "bank"),
                                           (salary[i], "out", "salary", "staff"),
                                           (rent[i], "out", "rent", "0011111111"),
                                           (50_000.0 if d.day == 15 else 0.0, "in", "own_transfer", "owner")):
            if amount:
                tx.append(dict(id=f"{i}-{cat}", date=d.isoformat(), amount=float(amount), direction=direction,
                               category=cat, counterparty_id=cp, purpose=""))
    return forecasters.History(dates=dates, inflow=revenue, outflow=salary + rent, missing=np.zeros(days, dtype=bool),
                               industry="Общепит", transactions=tuple(tx))


def strip(h: forecasters.History) -> forecasters.History:
    return forecasters.History(h.dates, h.inflow, h.outflow, h.missing, h.industry)


def test_registered_and_ready():
    assert forecasters.get("event_hybrid").ready


@pytest.mark.parametrize("with_transactions", [True, False])
def test_events_reconcile_with_daily_flows(with_transactions):
    h = company()
    h = h if with_transactions else strip(h)
    a = event_history(h).daily_amounts
    assert np.allclose(a[:, 0], h.inflow) and np.allclose(a[:, 1], h.outflow)


def test_mismatched_day_falls_back_to_daily_total():
    h = company()
    inflow = h.inflow.copy()
    inflow[100] += 7_000.0
    h = forecasters.History(h.dates, inflow, h.outflow, h.missing, h.industry, transactions=h.transactions)
    ev = event_history(h)
    assert np.allclose(ev.daily_amounts[:, 0], inflow)
    assert (ev.raw_events.date == str(h.dates[100])).sum() == 1


def test_missing_days_are_not_events():
    h = company()
    missing = h.missing.copy()
    missing[50:60] = True
    h = forecasters.History(h.dates, h.inflow, h.outflow, missing, h.industry, transactions=h.transactions)
    ev = event_history(h)
    assert np.isnan(ev.daily_amounts[50:60]).all() and not ev.known[50:60].any()


@pytest.mark.parametrize("with_transactions", [True, False])
def test_paths_contract_and_calendar(with_transactions):
    h = company()
    h = h if with_transactions else strip(h)
    p = forecasters.get("event_hybrid").forecast(h, 30, 300, np.random.default_rng(0))
    assert p.inflow.shape == p.outflow.shape == (300, 30)
    assert np.isfinite(p.inflow).all() and (p.inflow >= 0).all() and (p.outflow >= 0).all()
    if with_transactions:
        days = [h.dates[-1] + timedelta(days=i + 1) for i in range(30)]
        salary_day = next(i for i, d in enumerate(days) if d.day == 10 or (d.day in (11, 12) and d.weekday() == 0))
        assert p.outflow[:, salary_day].mean() > 200_000


def test_backtest_head_sees_no_future():
    h = company()
    cut = h.head(100)
    ev = event_history(cut)
    assert ev.raw_events.date.max() <= np.datetime64(cut.dates[-1])


def test_grpc_forecast_with_transactions():
    h = company()
    server, port = build_server("127.0.0.1:0", workers=2)
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
            stub = pb_grpc.ForecasterServiceStub(ch)
            history = [pb.DailyFlow(date=d.isoformat(), inflow=float(i_), outflow=float(o_))
                       for d, i_, o_ in zip(h.dates, h.inflow, h.outflow)]
            txs = [pb.HistoryTransaction(id=t["id"], date=t["date"], amount=t["amount"], direction=t["direction"],
                                         category=t["category"], counterparty_id=t["counterparty_id"],
                                         purpose=t["purpose"]) for t in h.transactions]
            resp = stub.Forecast(pb.ForecastRequest(model="event_hybrid", history=history, transactions=txs,
                                                    horizon_days=30, n_paths=100, seed=7))
            assert resp.model_used == "event_hybrid" and len(resp.paths) == 100 and len(resp.dates) == 30
    finally:
        server.stop(0)

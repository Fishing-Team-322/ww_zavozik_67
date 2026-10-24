"""Small synthetic histories for event-generator contract tests, not evaluation."""
import numpy as np
import pandas as pd

from zavozik_ml import calendar as cal
from zavozik_ml.event_forecasters.core import EventHistory


def history(days=240, seed=1, company_id="fixture"):
    rng = np.random.default_rng(seed)
    dates = np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + np.timedelta64(days, "D"))
    records = []
    for day in dates:
        if not cal.is_workday([day])[0]:
            continue
        stamp = pd.Timestamp(day)
        for _ in range(int(rng.poisson(1.8))):
            records.append(dict(date=stamp, direction=0, amount=float(rng.gamma(3, 100)),
                                category="sales", counterparty=""))
        if rng.random() < .45:
            records.append(dict(date=stamp, direction=1, amount=float(rng.gamma(2, 90)),
                                category="purchase", counterparty="supplier"))
        if stamp.day == 5:
            records.append(dict(date=stamp, direction=1, amount=900., category="rent", counterparty="landlord"))
    frame = pd.DataFrame(records, columns=["date", "direction", "amount", "category", "counterparty"])
    return EventHistory(company_id, "fixture_industry", dates, np.zeros(days, dtype=bool),
                        np.full(days, np.datetime64("NaT", "D")), frame)


def histories(n=4, days=240):
    return [history(days=days, seed=i + 1, company_id=f"fixture-{i}") for i in range(n)]

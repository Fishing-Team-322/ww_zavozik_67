"""Загрузка дневных потоков из выгрузки Go (`make export` → ml/data/flows.csv)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from zavozik_ml.forecasters.base import INTERNAL_CATEGORIES, History

DEFAULT_FLOWS = Path(__file__).resolve().parents[1] / "data" / "flows.csv"


@dataclass(frozen=True)
class Company:
    id: str
    history: History  # весь период
    balance: np.ndarray  # остаток на конец дня, nan — неизвестен

    def internal_net(self) -> np.ndarray:
        """Внутренние движения владельца за день со знаком."""
        return sum((self.history.category(c) for c in INTERNAL_CATEGORIES), np.zeros(len(self.history)))


def load_companies(path: Path | str = DEFAULT_FLOWS) -> list[Company]:
    df = pd.read_csv(path, dtype={"company_id": str, "industry": str}, parse_dates=["date"])
    cat_cols = [c for c in df.columns if c.startswith("cat_")]
    out = []
    for cid, g in df.groupby("company_id", sort=True):
        g = g.sort_values("date")
        history = History(
            dates=[d.date() for d in g["date"]],
            inflow=g["inflow"].to_numpy(float),
            outflow=g["outflow"].to_numpy(float),
            missing=g["missing"].to_numpy(bool),
            industry=str(g["industry"].iloc[0]) if "industry" in g else "",
            categories={c.removeprefix("cat_"): g[c].to_numpy(float) for c in cat_cols},
        )
        out.append(Company(id=cid, history=history, balance=g["balance"].to_numpy(float)))
    return out

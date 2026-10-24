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
    required = {"company_id", "date", "inflow", "outflow", "missing", "balance"}
    if not required <= set(df.columns):
        raise ValueError(f"missing daily-flow columns: {sorted(required-set(df.columns))}")
    if df.empty or df.company_id.isna().any() or df.date.isna().any():
        raise ValueError("daily flows must contain company IDs and dates")
    flags = df.missing.astype(str).str.lower().map({"true": True, "false": False, "1": True, "0": False})
    if flags.isna().any():
        raise ValueError("missing flags must be true/false or 1/0")
    df["missing"] = flags.astype(bool)
    cat_cols = [c for c in df.columns if c.startswith("cat_")]
    values = df[["inflow", "outflow", *cat_cols]].to_numpy(float)
    if not np.isfinite(values).all() or (values[:, :2] < 0).any():
        raise ValueError("daily flows must be finite; inflow/outflow must be nonnegative")
    if np.isinf(df.balance.to_numpy(float)).any():
        raise ValueError("balance must be finite or missing")
    out = []
    for cid, g in df.groupby("company_id", sort=True):
        g = g.sort_values("date")
        if not (g.date.diff().dropna() == pd.Timedelta(days=1)).all():
            raise ValueError(f"{cid}: dates must be unique consecutive calendar days")
        history = History(
            dates=[d.date() for d in g["date"]],
            inflow=g["inflow"].to_numpy(float),
            outflow=g["outflow"].to_numpy(float),
            missing=g["missing"].to_numpy(bool),
            industry=str(g["industry"].fillna("").iloc[0]) if "industry" in g else "",
            categories={c.removeprefix("cat_"): g[c].to_numpy(float) for c in cat_cols},
            missing_known_on=pd.to_datetime(g["missing_known_on"]).to_numpy(dtype="datetime64[D]")
            if "missing_known_on" in g else None,
        )
        out.append(Company(id=cid, history=history, balance=g["balance"].to_numpy(float)))
    return out

"""Датасет кейса → шард трансформера.

    python -m zavozik_ml.trx.prepare_case --out data/trx/case

Категории — метки правил Go (`ml/data/rule_labels.csv`, выгрузка
`backend/cmd/rulelabel`), тот же источник, что у классификатора. Позже их
заменит классификатор v2. Разбиение компаний — `eval/split_v2.json`:
у каждой последовательности атрибут `role` (development | audit), фильтр
делает dataset, а не подготовка, — один шард на все режимы.

Внутренние переводы владельца остаются в последовательности (тип
`case:own_transfer` / `case:owner_loan`): модель видит динамику счёта
целиком, а из бизнес-потока они исключаются при агрегации прогноза.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import DIR_IN, DIR_OUT, TypeVocab
from .shards import ShardWriter, encode_sequence

ML_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OPS = ML_DIR.parent / "cashflow_dataset_participants" / "all_operations.csv"
DEFAULT_LABELS = ML_DIR / "data" / "rule_labels.csv"
DEFAULT_SPLIT = ML_DIR / "eval" / "split_v2.json"


def load_operations(ops_path: Path, labels_path: Path) -> pd.DataFrame:
    ops = pd.read_csv(ops_path, sep=";", encoding="utf-8-sig",
                      dtype={"counterparty_inn": str, "company_id": str, "operation_id": str},
                      usecols=["company_id", "operation_id", "operation_date", "amount", "direction"])
    labels = pd.read_csv(labels_path, sep=";", dtype={"id": str, "category": str}, usecols=["id", "category"])
    df = ops.merge(labels, left_on="operation_id", right_on="id", how="left")
    df["category"] = df["category"].fillna("other")
    df["day"] = (pd.to_datetime(df["operation_date"]).values.astype("datetime64[D]").astype(np.int64))
    df["dir"] = np.where(df["direction"] == "Поступление", DIR_IN, DIR_OUT)
    return df.sort_values(["company_id", "day", "operation_id"], kind="stable")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ops", type=Path, default=DEFAULT_OPS)
    p.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    p.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    p.add_argument("--vocab", type=Path, default=None, help="начать со словаря предобученной модели (индексы сохраняются)")
    p.add_argument("--out", type=Path, default=ML_DIR / "data" / "trx" / "case")
    args = p.parse_args()

    split = json.loads(args.split.read_text())
    audit = set(split["audit_companies"])
    vocab = TypeVocab.load(args.vocab) if args.vocab else TypeVocab()

    df = load_operations(args.ops, args.labels)
    writer = ShardWriter(args.out, source="case", vocab=vocab)
    for cid, g in df.groupby("company_id", sort=True):
        types = np.array([vocab.add(f"case:{c}") for c in g["category"]], dtype=np.int64)
        fields = encode_sequence(g["day"].to_numpy(), g["dir"].to_numpy(), types, g["amount"].to_numpy(float))
        writer.add(cid, fields, role="audit" if cid in audit else "development")
    meta = writer.close(split=str(args.split.name), audit_start=split.get("audit_start"),
                        labels=str(args.labels.name))
    print(f"case: {meta.n_sequences} компаний, {meta.n_tokens} операций, типов в словаре {len(vocab)} -> {args.out}")


if __name__ == "__main__":
    main()

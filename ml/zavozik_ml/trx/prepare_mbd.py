"""MBD (huggingface.co/datasets/ai-lab/MBD) → шард для предобучения.

    python -m zavozik_ml.trx.prepare_mbd --trx <распакованный detail/trx> --out data/trx/mbd

Схема trx из README датасета: client_id, event_time, amount, event_type,
event_subtype, currency, src_type*, dst_type*, fold. Текста назначений нет.

Неизвестные заранее вещи определяются по данным и пишутся в meta.json:
  * направление: если в суммах есть отрицательные — знак суммы, иначе
    «неизвестно» (DIR_UNKNOWN; модель учит направление на данных кейса);
  * тип операции: `mbd:<event_type>_<event_subtype>`;
  * валюта: по умолчанию берём только самую частую (рубли), остальные
    отбрасываем — суммы в разных валютах несопоставимы.

Файлы обрабатываются по одному: клиент, разнесённый по нескольким файлам,
станет несколькими последовательностями (в meta — счётчик таких случаев).
Начать с MBD-mini, полный набор — только транзакции (гео и диалоги не нужны).
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .schema import DIR_IN, DIR_OUT, DIR_UNKNOWN, TypeVocab
from .shards import ShardWriter, encode_sequence

COLUMNS = ["client_id", "event_time", "amount", "event_type", "event_subtype", "currency"]


def parquet_files(root: Path) -> list[Path]:
    files = sorted(root.rglob("*.parquet")) if root.is_dir() else [root]
    if not files:
        raise SystemExit(f"нет parquet-файлов в {root}")
    return files


def probe(files: list[Path], max_rows: int = 2_000_000) -> dict:
    """Первые строки: есть ли отрицательные суммы, какая валюта главная."""
    seen = 0
    neg = 0
    cur: Counter = Counter()
    for f in files:
        t = pq.read_table(f, columns=["amount", "currency"]).to_pandas()
        neg += int((t["amount"] < 0).sum())
        cur.update(t["currency"].tolist())
        seen += len(t)
        if seen >= max_rows:
            break
    return {"rows_probed": seen, "negative_amounts": neg, "currency_counts": dict(cur.most_common(10))}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--trx", type=Path, required=True, help="каталог или файл parquet с транзакциями MBD")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--direction", choices=["auto", "sign", "unknown"], default="auto")
    p.add_argument("--currency", default="auto", help="код валюты; auto — самая частая; all — не фильтровать")
    p.add_argument("--min-len", type=int, default=32, help="короче — не берём (мало контекста)")
    p.add_argument("--max-files", type=int, default=0, help="ограничить число файлов (пробный прогон)")
    p.add_argument("--part", default="0/1", help="i/n: взять каждый n-й файл начиная с i — для параллельных процессов, каждый в свой --out")
    p.add_argument("--tz-hours", type=float, default=3.0, help="сдвиг event_time к местному времени перед взятием даты (UTC → МСК = 3)")
    args = p.parse_args()

    files = parquet_files(args.trx)
    i, n = (int(x) for x in args.part.split("/"))
    files = files[i::n]
    if args.max_files:
        files = files[: args.max_files]
    info = probe(files)
    direction = args.direction
    if direction == "auto":
        direction = "sign" if info["negative_amounts"] > 0 else "unknown"
    currency = args.currency
    if currency == "auto":
        currency = next(iter(info["currency_counts"]))
    if currency != "all":
        currency = float(currency)
    print(f"MBD: файлов {len(files)}, направление: {direction}, валюта: {currency}, проба: {info}")

    vocab = TypeVocab()
    writer = ShardWriter(args.out, source="mbd", vocab=vocab)
    split_clients = Counter()
    dropped_short = 0
    dropped_currency = 0
    for i, f in enumerate(files, 1):
        t = pq.read_table(f, columns=COLUMNS).to_pandas()
        if currency != "all":
            # Сравниваем числа: в одних файлах колонка целая (11), в других дробная (11.0, есть
            # пропуски) — строковое сравнение выкидывало такие файлы целиком.
            keep = pd.to_numeric(t["currency"], errors="coerce") == float(currency)
            dropped_currency += int((~keep).sum())
            t = t[keep]
        # event_time в UTC: без сдвига вечерние операции по Москве уехали бы на прошлый день.
        local = pd.to_datetime(t["event_time"]) + pd.Timedelta(hours=args.tz_hours)
        t["day"] = local.values.astype("datetime64[D]").astype(np.int64)
        t = t.sort_values(["client_id", "event_time"], kind="stable")
        for cid, g in t.groupby("client_id", sort=False):
            if len(g) < args.min_len:
                dropped_short += 1
                continue
            amount = g["amount"].to_numpy(float)
            if direction == "sign":
                d = np.where(amount < 0, DIR_OUT, DIR_IN)
            else:
                d = np.full(len(g), DIR_UNKNOWN)
            names = ("mbd:" + g["event_type"].astype(str) + "_" + g["event_subtype"].astype(str)).tolist()
            types = np.array([vocab.add(n) for n in names], dtype=np.int64)
            split_clients[str(cid)] += 1
            writer.add(str(cid), encode_sequence(g["day"].to_numpy(), d, types, amount), role="pretrain",
                       file=f.name)
        print(f"  [{i}/{len(files)}] {f.name}: всего последовательностей {len(writer.sequences)}", flush=True)
    meta = writer.close(direction=direction, currency=str(currency), probe=info, min_len=args.min_len, part=args.part, tz_hours=args.tz_hours,
                        dropped_short=dropped_short, dropped_currency=dropped_currency,
                        clients_split_across_files=sum(1 for v in split_clients.values() if v > 1))
    print(f"MBD: {meta.n_sequences} последовательностей, {meta.n_tokens} операций, типов {len(vocab)} -> {args.out}")


if __name__ == "__main__":
    main()

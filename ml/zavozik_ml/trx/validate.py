"""Проверка подготовленных шардов перед обучением.

    python -m zavozik_ml.trx.validate data/trx/case /mnt/d/mbd/shards/part_0 ... [--expect-tokens N]

Жёсткие проверки (ошибка — обучать нельзя):
  * поля в допустимых границах, типы в пределах словаря, флаги 0/1;
  * дни внутри последовательности не убывают, delta согласована с днями;
  * смещения последовательностей монотонны и сходятся с числом токенов;
  * последовательности не пересекаются между шардами (один клиент — в одном месте).
Отчёт (смотрим глазами): операций всего и против ожидаемого, нулевые суммы,
точные повторы операций, период и операции по месяцам, доля операций в
нерабочие дни, длины историй, редкие и частые типы.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from zavozik_ml import calendar as cal

from .schema import DELTA_FAR, MAX_OFF_BEFORE, N_AMOUNT, N_DIR
from .shards import Shard

CHUNK = 20_000_000


def check_shard(sh: Shard, errors: list[str], stats: Counter, months: Counter, types: Counter, lengths: list) -> None:
    name = sh.directory.name
    a = sh.arrays
    n = sh.meta.n_tokens
    off = sh.offsets
    if off[0] != 0 or off[-1] != n or np.any(np.diff(off) <= 0):
        errors.append(f"{name}: смещения последовательностей не сходятся с числом токенов")
    lengths.append(np.diff(off))
    nt = len(sh.vocab)
    starts = np.zeros(n, dtype=bool)
    starts[off[:-1]] = True
    for lo in range(0, n, CHUNK):
        hi = min(n, lo + CHUNK)
        day = np.asarray(a["day"][lo:hi]).astype(np.int64)
        delta = np.asarray(a["delta"][lo:hi]).astype(np.int64)
        st = starts[lo:hi]
        for field, low, high in (("delta", 0, DELTA_FAR), ("dir", 0, N_DIR - 1), ("type", 2, nt - 1),
                                 ("amount_bin", 0, N_AMOUNT - 1), ("weekday", 0, 6), ("dom", 0, 30),
                                 ("month", 0, 11), ("off_before", 0, MAX_OFF_BEFORE), ("flags", 0, 1)):
            v = np.asarray(a[field][lo:hi])
            if v.min() < low or v.max() > high:
                errors.append(f"{name}: поле {field} вне [{low}, {high}]: {v.min()}..{v.max()}")
        la = np.asarray(a["log_amount"][lo:hi])
        if not np.isfinite(la).all() or la.min() < 0:
            errors.append(f"{name}: log_amount с NaN/отрицательными")
        # Порядок дней внутри последовательности и согласованность delta.
        d = np.diff(day, prepend=day[:1])
        inner = ~st
        if lo > 0:
            inner[0] = not starts[lo]
            d[0] = day[0] - int(a["day"][lo - 1])
        if np.any(d[inner] < 0):
            errors.append(f"{name}: дни убывают внутри последовательности ({int((d[inner] < 0).sum())} мест)")
        expect = np.where(d > DELTA_FAR - 1, DELTA_FAR, np.maximum(d, 0))
        if np.any(delta[inner] != expect[inner]):
            errors.append(f"{name}: delta не совпадает с разностью дней ({int((delta[inner] != expect[inner]).sum())} мест)")

        amount = np.asarray(a["amount"][lo:hi])
        stats["tokens"] += hi - lo
        stats["zero_amount"] += int((amount == 0).sum())
        stats["over_100m"] += int((amount > 1e8).sum())
        typ = np.asarray(a["type"][lo:hi])
        # Точный повтор: тот же день, тип и сумма, что у предыдущей операции клиента.
        same = (d == 0) & inner & (typ == np.roll(typ, 1)) & (amount == np.roll(amount, 1))
        stats["exact_repeat"] += int(same.sum())
        work = cal.is_workday(day.astype("datetime64[D]"))
        stats["nonworking"] += int((~work).sum())
        m = day.astype("datetime64[D]").astype("datetime64[M]").astype(str)
        months.update(Counter(m.tolist()))
        names = sh.vocab.names
        for t_id, cnt in zip(*np.unique(typ, return_counts=True)):
            types[names[t_id]] += int(cnt)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("shards", nargs="+", type=Path)
    p.add_argument("--expect-tokens", type=int, default=0, help="операций в исходнике (для сверки)")
    args = p.parse_args()

    errors: list[str] = []
    stats: Counter = Counter()
    months: Counter = Counter()
    types: Counter = Counter()
    lengths: list = []
    seen: dict[str, str] = {}
    meta_notes = []
    for path in args.shards:
        sh = Shard(path)
        meta_notes.append((path.name, sh.meta.notes))
        for s in sh.sequences:
            key = s["id"]
            if key in seen:
                errors.append(f"последовательность {key} есть и в {seen[key]}, и в {path.name}")
            seen[key] = path.name
        check_shard(sh, errors, stats, months, types, lengths)
        print(f"{path.name}: {sh.meta.n_sequences:,} последовательностей, {sh.meta.n_tokens:,} операций — проверено", flush=True)

    L = np.concatenate(lengths)
    tok = stats["tokens"]
    print("\n=== Отчёт ===")
    print(f"последовательностей: {len(L):,}; операций: {tok:,}")
    if args.expect_tokens:
        dropped = sum(n.get("dropped_currency", 0) for _, n in meta_notes)
        short = sum(n.get("dropped_short", 0) for _, n in meta_notes)
        print(f"в исходнике: {args.expect_tokens:,}; не взяли: {args.expect_tokens - tok:,} "
              f"({(args.expect_tokens - tok) / args.expect_tokens:.2%}); из них другая валюта: {dropped:,}; "
              f"клиентов с короткой историей отброшено: {short:,}")
    print(f"нулевые суммы: {stats['zero_amount']:,} ({stats['zero_amount'] / tok:.2%})")
    print(f"суммы больше 100 млн: {stats['over_100m']:,} ({stats['over_100m'] / tok:.3%})")
    print(f"точные повторы (тот же день, тип и сумма подряд): {stats['exact_repeat']:,} ({stats['exact_repeat'] / tok:.2%})")
    print(f"операции в нерабочие дни по календарю РФ: {stats['nonworking']:,} ({stats['nonworking'] / tok:.2%})")
    q = np.percentile(L, [1, 10, 50, 90, 99]).astype(int)
    print(f"длина истории (операций): 1%={q[0]} 10%={q[1]} медиана={q[2]} 90%={q[3]} 99%={q[4]} макс={L.max()}")
    ms = sorted(months.items())
    print(f"период: {ms[0][0]} — {ms[-1][0]}; операций по месяцам: мин {min(v for _, v in ms):,}, макс {max(v for _, v in ms):,}")
    print("  " + ", ".join(f"{k}:{v / 1e6:.1f}м" for k, v in ms))
    rare = [t for t, c in types.items() if c < 1000]
    print(f"типов: {len(types)}; редких (<1000 операций): {len(rare)}, в них {sum(types[t] for t in rare):,} операций")
    print("частые типы:", ", ".join(f"{t} {c / tok:.1%}" for t, c in types.most_common(8)))
    if errors:
        print("\n=== ОШИБКИ — обучать нельзя ===")
        for e in errors[:50]:
            print(" -", e)
        sys.exit(1)
    print("\nжёсткие проверки пройдены: VALID")


if __name__ == "__main__":
    main()

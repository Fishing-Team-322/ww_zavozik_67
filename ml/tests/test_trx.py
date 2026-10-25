"""Трансформер транзакций: формат данных, обучение, генерация.

Нужен torch — в прод-окружении без него тесты пропускаются.
Запуск: PYTHONPATH=gen:. ml/data/chronos_venv/bin/python -m pytest tests/test_trx.py -q
"""

from datetime import date, timedelta

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from zavozik_ml import calendar as cal  # noqa: E402
from zavozik_ml.trx import schema  # noqa: E402
from zavozik_ml.trx.dataset import Source, WindowDataset, build_vocab, collate, validation_windows  # noqa: E402
from zavozik_ml.trx.generate import context_tokens, generate  # noqa: E402
from zavozik_ml.trx.model import TrxConfig, TrxGPT  # noqa: E402
from zavozik_ml.trx.shards import Shard, ShardWriter, encode_sequence  # noqa: E402


def day_number(d: date) -> int:
    return int(np.datetime64(d, "D").astype(np.int64))


def company_ops(start: date, days: int, seed: int):
    """Рабочие дни: выручка каждый день, зарплата 10-го и 25-го, ЕНП 28-го,
    иногда перевод владельца."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(days):
        d = start + timedelta(days=i)
        n = day_number(d)
        if not cal.is_workday(np.array([n], dtype="datetime64[D]"))[0]:
            continue
        rows.append((n, schema.DIR_IN, "case:revenue_acquiring", rng.gamma(4, 20_000)))
        if d.day in (10, 25):
            rows.append((n, schema.DIR_OUT, "case:salary", 150_000.0))
        if d.day == 28:
            rows.append((n, schema.DIR_OUT, "case:tax", 60_000.0))
        if rng.random() < 0.02:
            rows.append((n, schema.DIR_IN, "case:owner_loan", 500_000.0))
    return rows


@pytest.fixture(scope="module")
def shard(tmp_path_factory):
    path = tmp_path_factory.mktemp("case")
    vocab = schema.TypeVocab()
    w = ShardWriter(path, "case", vocab)
    for c in range(6):
        rows = company_ops(date(2025, 1, 1), 300, c)
        days, dirs, names, amounts = map(np.array, zip(*rows))
        types = np.array([vocab.add(n) for n in names])
        w.add(f"C{c:03d}", encode_sequence(days, dirs, types, amounts.astype(float)),
              role="audit" if c == 5 else "development")
    w.close()
    return Shard(path)


def tiny_model(n_types: int) -> TrxGPT:
    return TrxGPT(TrxConfig(n_types=n_types, d_model=64, n_layers=2, n_heads=4, d_ff=128, max_len=128, dropout=0.0))


def test_schema_encoding_roundtrip():
    a = np.array([1.0, 999.0, 150_000.0, 3e8])
    b = schema.amount_bin(a)
    back = schema.amount_from_bin(b)
    assert np.all(np.abs(np.log10(back) - np.log10(a)) < 9 / schema.N_AMOUNT)
    d = np.array([100, 100, 103, 200])
    assert schema.delta_days(d).tolist() == [0, 0, 3, schema.DELTA_FAR]
    c = schema.calendar_fields(np.array([day_number(date(2025, 12, 29))]))
    assert c["weekday"][0] == 0 and c["dom"][0] == 28 and c["month"][0] == 11
    assert c["flags"][0].tolist() == [1, 1, 0, 0]  # рабочий; ЕНП перенесён с вс 28-го на пн 29-е


def test_shard_roundtrip_and_roles(shard):
    assert len(shard) == 6 and shard.meta.source == "case"
    t = shard.slice(0)
    assert np.all(np.diff(t["day"]) >= 0) and t["flags"].shape[1] == 4
    src = Source(shard, roles={"development"}, max_day=day_number(date(2025, 6, 30)))
    vocab = build_vocab([src])
    ds = WindowDataset([src], seq_len=64)
    ex = next(iter(ds))
    assert ex["x_delta"].shape == (64,) and ex["x_day"].max() <= src.max_day  # отсечка соблюдена
    b = collate([ex, next(iter(ds))])
    assert b["x_type"].dtype == torch.int64 and b["mask"].all() and len(vocab) == len(shard.vocab)


def test_tiny_model_learns(shard):
    src = Source(shard, roles={"development"})
    vocab = build_vocab([src])
    model = tiny_model(len(vocab))
    windows = validation_windows([src], 64, 8)
    b = collate(windows)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3)
    first = float(model(b)["loss"])
    for _ in range(150):
        loss = model(b)["loss"]
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert float(model(b)["loss"]) < first * 0.5


def test_generation_respects_calendar_horizon_and_internal(shard):
    src = Source(shard)
    vocab = build_vocab([src])
    model = tiny_model(len(vocab))
    tok = shard.slice(5)
    origin = day_number(date(2025, 9, 30))
    upto = int(np.searchsorted(tok["day"], origin, side="right"))
    ctx = context_tokens({k: v[:upto] for k, v in tok.items()}, src.remap, "case")
    g = generate(model, ctx, vocab, origin, horizon=30, n_paths=16, seed=1)
    assert g.business_in.shape == (16, 30)
    days = origin + 1 + np.arange(30)
    off = ~cal.is_workday(days.astype("datetime64[D]"))
    assert (g.business_in[:, off] == 0).all() and (g.business_out[:, off] == 0).all()
    assert (g.business_in >= 0).all() and (g.business_out >= 0).all()
    assert g.n_ops.sum() > 0
    per_day = np.unique(ctx["day"], return_counts=True)[1].max()
    assert g.n_ops.max() <= 30 * max(3, int(np.ceil(1.5 * per_day)))  # нет лавины операций в один день


def test_resize_types_keeps_old_rows():
    model = tiny_model(10)
    before = model.type_emb.weight[:10].clone()
    model.resize_types(14)
    assert model.type_emb.num_embeddings == 14 and model.head_type[-1].out_features == 14
    assert torch.equal(model.type_emb.weight[:10], before)


def test_checkpoint_roundtrip(tmp_path, shard):
    from argparse import Namespace

    from zavozik_ml.trx.train import load_model, save_checkpoint

    vocab = build_vocab([Source(shard)])
    model = tiny_model(len(vocab))
    save_checkpoint(tmp_path / "m.pt", model, None, 7, 1.5, vocab, Namespace(out=tmp_path, lr=1e-3))
    m2, v2, ck = load_model(tmp_path / "m.pt")
    assert v2.names == vocab.names and ck["step"] == 7 and ck["args"]["out"] == str(tmp_path)
    for a, b in zip(model.state_dict().values(), m2.state_dict().values()):
        assert torch.equal(a, b)


def test_buckets_split_companies_without_overlap(shard):
    from zavozik_ml.trx.dataset import _eligible
    from zavozik_ml.trx.train import parse_source

    a = parse_source(f"{shard.directory}:development[0-50]")
    b = parse_source(f"{shard.directory}:development[50-100]")
    ia, ib = set(_eligible(a, 16)[0].tolist()), set(_eligible(b, 16)[0].tolist())
    assert a.buckets == (0, 50) and a.roles == {"development"}
    assert not ia & ib and len(ia | ib) == 5  # все компании разработки, без пересечения


def test_augment_keeps_window_valid(shard):
    from zavozik_ml.trx.dataset import Augment, make_example

    src = Source(shard)
    build_vocab([src])
    base = make_example(src, 0, 0, 64)
    ex = make_example(src, 0, 0, 64, Augment(scale_std=0.5, drop=0.3), np.random.default_rng(0))
    assert len(ex["x_delta"]) < len(base["x_delta"]) and len(ex["x_delta"]) == len(ex["y_amount_bin"])
    assert ex["x_amount_bin"].min() >= 0 and ex["x_amount_bin"].max() < schema.N_AMOUNT
    assert ex["y_delta"].min() >= 0 and ex["y_delta"].max() <= schema.DELTA_FAR
    assert np.all(np.diff(np.concatenate([ex["x_day"][:1], ex["x_day"]])) >= 0)


def test_layer_decay_groups():
    from zavozik_ml.trx.model import param_groups

    model = tiny_model(10)
    groups = param_groups(model, 0.1, layer_decay=0.5)
    scales = {id(p): g["lr_scale"] for g in groups for p in g["params"]}
    assert scales[id(model.type_emb.weight)] == 0.5 ** 3  # 2 слоя: эмбеддинги — самый малый шаг
    assert scales[id(model.blocks[0].qkv.weight)] == 0.25 and scales[id(model.blocks[1].qkv.weight)] == 0.5
    assert scales[id(model.head_amount[0].weight)] == 1.0
    assert sum(len(g["params"]) for g in groups) == len(list(model.parameters()))


def test_resume_keeps_schedule_and_ema(tmp_path, shard):
    from zavozik_ml.trx.train import build_parser, run

    common = ["--data", f"{shard.directory}:development", "--val", f"{shard.directory}:audit",
              "--d-model", "32", "--layers", "1", "--heads", "2", "--d-ff", "64", "--seq-len", "32",
              "--batch", "4", "--val-windows", "4", "--workers", "0", "--device", "cpu", "--ema", "0.9"]
    out = tmp_path / "run"
    run(build_parser().parse_args(common + ["--out", str(out), "--max-steps", "60", "--eval-every", "20",
                                            "--patience", "7", "--time-limit-min", "0.0001"]))
    ck = torch.load(out / "last.pt", weights_only=False)
    assert 0 < ck["step"] < 60 and ck["ema"] is not None
    # Продолжение без флагов — те же max_steps / eval_every / patience, а не значения по умолчанию.
    run(build_parser().parse_args(["--resume", str(out)]))
    ck = torch.load(out / "last.pt", weights_only=False)
    assert ck["step"] == 60 and ck["args"]["patience"] == 7 and ck["args"]["eval_every"] == 20


def test_window_sampling_follows_length_weights(shard):
    src = Source(shard, roles={"development"})
    build_vocab([src])
    ds = WindowDataset([src], seq_len=16)
    rng = np.random.default_rng(0)
    picks = [min(int(np.searchsorted(ds._cdf, rng.random() * ds._cdf[-1], side="right")), len(ds._flat) - 1)
             for _ in range(20000)]
    freq = np.bincount(picks, minlength=len(ds._flat)) / len(picks)
    assert np.abs(freq - ds._p).max() < 0.02


def test_time_budget_sets_steps(tmp_path, shard):
    from zavozik_ml.trx.train import build_parser, run

    args = build_parser().parse_args([
        "--data", f"{shard.directory}:development", "--val", f"{shard.directory}:audit", "--out", str(tmp_path / "r"),
        "--d-model", "32", "--layers", "1", "--heads", "2", "--d-ff", "64", "--seq-len", "32", "--batch", "4",
        "--val-windows", "4", "--workers", "0", "--device", "cpu", "--max-steps", "10000000",
        "--time-budget-min", "0.15", "--n-evals", "3"])
    run(args)
    ck = torch.load(tmp_path / "r" / "last.pt", weights_only=False)
    assert 220 < ck["args"]["max_steps"] < 10000000 and ck["step"] == ck["args"]["max_steps"]


def test_amount_cap_and_top_p_limit_generated_sums(shard):
    src = Source(shard)
    vocab = build_vocab([src])
    model = tiny_model(len(vocab))
    tok = shard.slice(0)
    origin = day_number(date(2025, 9, 30))
    upto = int(np.searchsorted(tok["day"], origin, side="right"))
    ctx = context_tokens({k: v[:upto] for k, v in tok.items()}, src.remap, "case")
    hist_max = float(np.power(10.0, ctx["log_amount"].astype(float) * schema.AMOUNT_LOG_MAX).max())
    g = generate(model, ctx, vocab, origin, horizon=20, n_paths=16, seed=2, cap_mult=1.0, amount_top_p=0.9)
    day_max = max(g.business_in.max(), g.business_out.max(), np.abs(g.internal_net).max())
    assert g.n_ops.sum() > 0
    # Потолок — по интервалу суммы: не больше верхней границы интервала максимума истории (×1,18) на операцию.
    assert day_max <= hist_max * 1.2 * g.n_ops.max()

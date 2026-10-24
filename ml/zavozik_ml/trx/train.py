"""Обучение TrxGPT: предобучение и дообучение одним скриптом.

Источник данных: `путь[:роли[:дата_отсечки[:вес]]]`, роли через запятую.

    # предобучение на MBD
    python -m zavozik_ml.trx.train --data data/trx/mbd --out runs/pretrain --max-steps 200000

    # дообучение на компаниях разработки кейса, только данные до начала аудита
    python -m zavozik_ml.trx.train --init runs/pretrain/best.pt \\
        --data data/trx/case:development:2026-06-30 \\
        --val data/trx/case:development:2026-06-30 --out runs/finetune --lr 1e-4 --max-steps 20000

    # продолжить прерванное обучение (все параметры запуска берутся из last.pt)
    python -m zavozik_ml.trx.train --resume runs/pretrain

Роли можно сузить корзинами хеша компании: `development[0-80]` — 80% компаний
разработки для обучения, `development[80-100]` — остальные 20% для валидации.

Контрольная точка last.pt пишется каждые --ckpt-minutes и в конце, best.pt —
при лучшей валидационной потере, final.pt — в конце (оба — веса EMA, если
--ema). bf16 на CUDA включается сам.
Подбор гиперпараметров — `tune.py` (Optuna) поверх `run()` отсюда.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import re
import time
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from .dataset import Augment, Source, WindowDataset, build_vocab, collate, validation_windows
from .model import TrxConfig, TrxGPT, cosine_lr, param_groups
from .schema import TypeVocab
from .shards import Shard


def parse_source(spec: str) -> Source:
    parts = spec.split(":")
    # Windows: «C:\data\...» — первая часть с буквой диска
    if len(parts) > 1 and len(parts[0]) == 1 and parts[1].startswith(("\\", "/")):
        parts = [parts[0] + ":" + parts[1]] + parts[2:]
    path = Path(parts[0])
    roles_spec = parts[1] if len(parts) > 1 else ""
    buckets = None
    m = re.fullmatch(r"(.*)\[(\d+)-(\d+)\]", roles_spec)
    if m:
        roles_spec, buckets = m.group(1), (int(m.group(2)), int(m.group(3)))
    roles = set(roles_spec.split(",")) if roles_spec else None
    max_day = int(np.datetime64(parts[2], "D").astype(np.int64)) if len(parts) > 2 and parts[2] else None
    weight = float(parts[3]) if len(parts) > 3 and parts[3] else 1.0
    return Source(Shard(path), roles=roles, max_day=max_day, weight=weight, buckets=buckets)


def pick_device(name: str) -> torch.device:
    if name != "auto":
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def to_device(b: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {k: v.to(device, non_blocking=True) for k, v in b.items()}


def save_checkpoint(path: Path, model: TrxGPT, opt, step: int, best: float, vocab: TypeVocab, args,
                    stale: int = 0, ema: "Ema | None" = None) -> None:
    tmp = path.with_suffix(".tmp")
    torch.save({
        "model": model.state_dict(), "config": model.cfg.to_dict(), "vocab": vocab.names,
        "optimizer": opt.state_dict() if opt is not None else None, "step": step, "best_val": best,
        "stale": stale, "ema": ema.shadow if ema is not None else None,
        # Path → str: точка, сохранённая на Mac/Linux, должна открываться в Windows и наоборот.
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "torch_rng": torch.get_rng_state(), "numpy_rng": np.random.get_state(),
    }, tmp)
    os.replace(tmp, path)  # атомарно: обрыв посреди записи не портит прошлую точку


def load_model(path: Path, map_location="cpu") -> tuple[TrxGPT, TypeVocab, dict]:
    ck = torch.load(path, map_location=map_location, weights_only=False)
    known = {f.name for f in fields(TrxConfig)}
    cfg = TrxConfig(**{k: (tuple(v) if k == "loss_weights" else v) for k, v in ck["config"].items() if k in known})
    model = TrxGPT(cfg)
    model.load_state_dict(ck["model"])
    return model, TypeVocab(ck["vocab"]), ck


class Ema:
    """Скользящее среднее весов: сглаживает шум последних шагов, на малых данных
    заметно снижает переобучение. Валидация и best.pt — на усреднённых весах."""

    def __init__(self, model: nn.Module, decay: float, shadow: dict | None = None):
        self.decay = decay
        live = model.state_dict()
        self.names = [k for k, v in live.items() if v.dtype.is_floating_point]
        self.live = [live[k] for k in self.names]  # те же тензоры, что у модели
        self.shadow = shadow or {k: live[k].detach().clone() for k in self.names}
        self._shadow = [self.shadow[k] for k in self.names]
        self.updates = 0

    @torch.no_grad()
    def update(self) -> None:
        self.updates += 1
        d = min(self.decay, (1 + self.updates) / (10 + self.updates))  # короткий разгон в начале
        torch._foreach_lerp_(self._shadow, self.live, 1 - d)

    @contextmanager
    def applied(self, model: nn.Module):
        backup = [t.detach().clone() for t in self.live]
        with torch.no_grad():
            torch._foreach_copy_(self.live, self._shadow)
        try:
            yield
        finally:
            with torch.no_grad():
                torch._foreach_copy_(self.live, backup)


def _eval_reserve(args, per_step: float) -> float:
    """Секунды на проверки до конца запуска (оценка: проверка ≈ шаг на каждые batch окон)."""
    n = args.n_evals or 8
    return n * (args.val_windows / max(args.batch, 1)) * per_step * 0.5


@contextmanager
def _nothing():
    yield


@torch.no_grad()
def evaluate(model: TrxGPT, windows: list[dict], device, amp_dtype, batch: int) -> dict[str, float]:
    model.eval()
    sums: dict[str, float] = {}
    count = 0
    for i in range(0, len(windows), batch):
        b = to_device(collate(windows[i : i + batch]), device)
        with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            out = model(b)
        for k, v in out.items():
            sums[k] = sums.get(k, 0.0) + float(v)
        count += 1
    model.train()
    return {k: v / max(count, 1) for k, v in sums.items()}


# Параметры, которые при --resume можно задать заново; остальное — из last.pt.
RUNTIME_ARGS = {"resume", "out", "workers", "device", "time_limit_min", "ckpt_minutes", "compile"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", action="append", default=[], help="источник для обучения (можно несколько)")
    p.add_argument("--val", action="append", default=[], help="источник для валидации; по умолчанию — окна из --data")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--resume", type=Path, default=None, help="каталог запуска с last.pt")
    p.add_argument("--init", type=Path, default=None, help="веса предобученной модели для дообучения")
    # модель
    p.add_argument("--d-model", type=int, default=256)
    p.add_argument("--layers", type=int, default=6)
    p.add_argument("--heads", type=int, default=8)
    p.add_argument("--d-ff", type=int, default=1024)
    p.add_argument("--seq-len", type=int, default=512)
    p.add_argument("--dropout", type=float, default=0.1, help="при --init заменяет dropout предобученной модели")
    # обучение
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--accum", type=int, default=1, help="накопление градиентов (эффективный батч = batch × accum)")
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--weight-decay", type=float, default=0.1)
    p.add_argument("--warmup", type=int, default=1000)
    p.add_argument("--warmup-frac", type=float, default=0, help="разогрев как доля --max-steps (вместо --warmup)")
    p.add_argument("--max-steps", type=int, default=50000)
    p.add_argument("--token-budget", type=float, default=0,
                   help="сколько операций пройти; задаёт --max-steps = бюджет / (batch × accum × seq-len)")
    p.add_argument("--layer-decay", type=float, default=1.0, help="послойный шаг обучения (<1 — для дообучения)")
    p.add_argument("--ema", type=float, default=0, help="EMA весов, например 0.999 (0 — выключено)")
    p.add_argument("--aug-scale", type=float, default=0, help="σ логарифма случайного множителя сумм окна")
    p.add_argument("--aug-drop", type=float, default=0, help="доля случайно выкидываемых операций окна")
    p.add_argument("--time-limit-min", type=float, default=0, help="остановиться через N минут (0 — без лимита)")
    p.add_argument("--eval-every", type=int, default=1000)
    p.add_argument("--patience", type=int, default=0,
                   help="ранняя остановка: стоп, если вал. потеря не улучшалась N проверок подряд (0 — выключено)")
    p.add_argument("--min-delta", type=float, default=0.0,
                   help="улучшение вал. потери меньше этого считается «не сдвинулась» (для --patience)")
    p.add_argument("--time-budget-min", type=float, default=0,
                   help="уложиться в N минут: после замера скорости --max-steps подгоняется так, "
                        "чтобы расписание шага обучения закончилось к сроку")
    p.add_argument("--n-evals", type=int, default=0, help="сколько проверок за запуск (вместо --eval-every)")
    p.add_argument("--val-windows", type=int, default=512)
    p.add_argument("--ckpt-minutes", type=float, default=20)
    p.add_argument("--min-len", type=int, default=16)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--device", default="auto")
    p.add_argument("--precision", choices=["auto", "bf16", "fp32"], default="auto")
    p.add_argument("--compile", action="store_true", help="torch.compile (в Windows нужен WSL2/Triton)")
    p.add_argument("--seed", type=int, default=42)
    return p


def main() -> None:
    p = build_parser()
    args = p.parse_args()
    if not args.resume and (not args.data or args.out is None):
        p.error("нужны --data и --out (или --resume)")
    run(args)


def run(args, trial=None) -> float:
    """Обучение; возвращает лучшую валидационную потерю. trial — испытание Optuna:
    ему сообщается потеря на каждой проверке, слабые испытания обрываются (TrialPruned)."""
    resume_ck = None
    if args.resume:
        resume_ck = torch.load(Path(args.resume) / "last.pt", map_location="cpu", weights_only=False)
        # Всё, кроме параметров среды, — как в прерванном запуске: иначе другое
        # расписание шага обучения и число шагов (баг: продолжение обрезалось на 50 000).
        for k, v in resume_ck["args"].items():
            if k not in RUNTIME_ARGS and hasattr(args, k):
                setattr(args, k, v)
        args.out = Path(args.resume)
    args.out = Path(args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.token_budget:
        args.max_steps = max(1, int(args.token_budget // (args.batch * args.accum * args.seq_len)))
    if args.warmup_frac:
        args.warmup = max(1, int(args.warmup_frac * args.max_steps))
    if args.n_evals:
        args.eval_every = max(1, args.max_steps // args.n_evals)

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = pick_device(args.device)
    use_bf16 = args.precision == "bf16" or (args.precision == "auto" and device.type == "cuda" and torch.cuda.is_bf16_supported())
    amp_dtype = torch.bfloat16 if use_bf16 else None
    if device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

    sources = [parse_source(s) for s in args.data]
    val_sources = [parse_source(s) for s in args.val] if args.val else [parse_source(s) for s in args.data]

    # Словарь и модель: новая, из предобученной (с расширением словаря) или из last.pt.
    base_vocab = None
    init_model = None
    if resume_ck is not None:
        base_vocab = TypeVocab(resume_ck["vocab"])
    elif args.init:
        init_model, base_vocab, _ = load_model(args.init)
    vocab = build_vocab(sources + val_sources, base=base_vocab)

    if resume_ck is not None:
        known = {f.name for f in fields(TrxConfig)}
        cfg = TrxConfig(**{k: (tuple(v) if k == "loss_weights" else v) for k, v in resume_ck["config"].items() if k in known})
        model = TrxGPT(cfg)
        model.load_state_dict(resume_ck["model"])
        model.resize_types(len(vocab))
    elif init_model is not None:
        model = init_model
        model.resize_types(len(vocab))
        model.set_dropout(args.dropout)
    else:
        cfg = TrxConfig(n_types=len(vocab), d_model=args.d_model, n_layers=args.layers, n_heads=args.heads,
                        d_ff=args.d_ff, max_len=args.seq_len, dropout=args.dropout)
        model = TrxGPT(cfg)
    if args.seq_len > model.cfg.max_len:
        raise SystemExit(f"--seq-len {args.seq_len} больше max_len модели {model.cfg.max_len}")
    model.to(device)

    opt = torch.optim.AdamW(param_groups(model, args.weight_decay, args.layer_decay), lr=args.lr, betas=(0.9, 0.95),
                            fused=device.type == "cuda")
    step, best, stale = 0, math.inf, 0  # stale — проверок подряд без улучшения валидационной потери
    ema_shadow = None
    if resume_ck is not None:
        opt.load_state_dict(resume_ck["optimizer"])
        step, best, stale = resume_ck["step"], resume_ck["best_val"], resume_ck.get("stale", 0)
        ema_shadow = resume_ck.get("ema")
        torch.set_rng_state(resume_ck["torch_rng"])
        np.random.set_state(resume_ck["numpy_rng"])
    ema = None
    if args.ema:
        if ema_shadow is not None:
            ema_shadow = {k: v.to(device) for k, v in ema_shadow.items()}
        ema = Ema(model, args.ema, ema_shadow)

    aug = Augment(args.aug_scale, args.aug_drop)
    train_ds = WindowDataset(sources, args.seq_len, args.min_len, seed=args.seed + step, aug=aug or None)
    loader = DataLoader(train_ds, batch_size=args.batch, collate_fn=collate, num_workers=args.workers,
                        pin_memory=device.type == "cuda", persistent_workers=args.workers > 0)
    val = validation_windows(val_sources, args.seq_len, args.val_windows, args.min_len)
    fwd = torch.compile(model) if args.compile else model

    vocab.save(args.out / "vocab.json")
    (args.out / "config.json").write_text(json.dumps({"model": model.cfg.to_dict(), "args": {k: str(v) for k, v in vars(args).items()}},
                                                     ensure_ascii=False, indent=1))
    print(f"устройство {device} ({'bf16' if use_bf16 else 'fp32'}), параметров {model.n_params() / 1e6:.1f} млн, "
          f"типов {len(vocab)}, обучающих операций {train_ds.n_tokens():,}, шагов {args.max_steps:,} "
          f"(~{args.max_steps * args.batch * args.accum * args.seq_len / max(train_ds.n_tokens(), 1):.1f} эпох), "
          f"ОС {platform.system()}", flush=True)

    log_path = args.out / "log.csv"
    new_log = not log_path.exists()
    log_f = open(log_path, "a", newline="")
    log = csv.writer(log_f)
    if new_log:
        log.writerow(["step", "lr", "loss", "delta", "dir", "type", "amount", "val_loss", "val_delta", "val_dir",
                      "val_type", "val_amount", "tokens_per_s", "elapsed_min"])

    n_evals = 0
    budget_from = step  # бюджет времени подгоняется только в новом запуске, не при продолжении
    t_start = time.time()
    t_ckpt = time.time()
    t_window = time.time()
    tokens_window = 0
    model.train()
    it = iter(loader)
    try:
        while step < args.max_steps:
            lr = cosine_lr(step, args.warmup, args.max_steps, args.lr)
            for g in opt.param_groups:
                g["lr"] = lr * g.get("lr_scale", 1.0)
            acc: dict[str, float] = {}
            for _ in range(args.accum):
                b = to_device(next(it), device)
                with torch.autocast(device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
                    out = fwd(b)
                (out["loss"] / args.accum).backward()
                tokens_window += int(b["mask"].sum())
                for k, v in out.items():
                    acc[k] = acc.get(k, 0.0) + float(v.detach()) / args.accum
            if not math.isfinite(acc["loss"]):
                raise FloatingPointError(f"потеря {acc['loss']} на шаге {step}: слишком большой шаг обучения?")
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            if ema is not None:
                ema.update()
            step += 1
            if step == 20:
                t_20 = time.time()  # к 20-му шагу процессы загрузки и компиляция уже прогреты
            if args.time_budget_min and budget_from == 0 and step == 220:
                # Замер скорости на шагах 20–220 → столько шагов, сколько успеем к сроку.
                per_step = (time.time() - t_20) / 200
                left = args.time_budget_min * 60 - (time.time() - t_start) - _eval_reserve(args, per_step)
                args.max_steps = max(step + 1, step + int(left / per_step))
                if args.warmup_frac:
                    args.warmup = max(1, int(args.warmup_frac * args.max_steps))
                if args.n_evals:
                    args.eval_every = max(1, args.max_steps // args.n_evals)
                print(f"бюджет {args.time_budget_min:g} мин: {per_step * 1000:.0f} мс/шаг → {args.max_steps:,} шагов", flush=True)

            last_eval = step % args.eval_every == 0 or step == args.max_steps
            if step % 50 == 0 or last_eval:
                dt = max(time.time() - t_window, 1e-9)
                tps = tokens_window / dt
                t_window, tokens_window = time.time(), 0
                row = [step, f"{lr:.2e}"] + [f"{acc[k]:.4f}" for k in ("loss", "delta", "dir", "type", "amount")]
                vrow = [""] * 5
                if last_eval:
                    with ema.applied(model) if ema is not None else _nothing():
                        v = evaluate(model, val, device, amp_dtype, args.batch)
                        if v["loss"] < best - args.min_delta:
                            best, stale = v["loss"], 0
                            save_checkpoint(args.out / "best.pt", model, None, step, best, vocab, args)
                        else:
                            stale += 1
                            if v["loss"] < best:  # чуть лучше, но меньше порога: точку сохраняем, счётчик идёт
                                best = v["loss"]
                                save_checkpoint(args.out / "best.pt", model, None, step, best, vocab, args)
                    vrow = [f"{v[k]:.4f}" for k in ("loss", "delta", "dir", "type", "amount")]
                log.writerow(row + vrow + [f"{tps:.0f}", f"{(time.time() - t_start) / 60:.1f}"])
                log_f.flush()
                print(f"шаг {step}: loss {acc['loss']:.3f} (дни {acc['delta']:.3f}, напр. {acc['dir']:.3f}, тип {acc['type']:.3f}, "
                      f"сумма {acc['amount']:.3f})" + (f" | вал. {vrow[0]}" if last_eval else "") + f" | {tps:,.0f} операций/с",
                      flush=True)
                if last_eval and trial is not None:
                    import optuna

                    trial.report(v["loss"], n_evals)
                    trial.set_user_attr("best_step", step if stale == 0 else trial.user_attrs.get("best_step", step))
                    if trial.should_prune():
                        raise optuna.TrialPruned(f"шаг {step}: вал. {v['loss']:.4f}")
                n_evals += last_eval
            if (time.time() - t_ckpt) / 60 >= args.ckpt_minutes:
                save_checkpoint(args.out / "last.pt", model, opt, step, best, vocab, args, stale, ema)
                t_ckpt = time.time()
            if args.patience and stale >= args.patience:
                print(f"ранняя остановка: валидационная потеря не улучшалась {stale} проверок подряд")
                break
            if args.time_limit_min and (time.time() - t_start) / 60 >= args.time_limit_min:
                print("лимит времени — останавливаюсь")
                break
        save_checkpoint(args.out / "last.pt", model, opt, step, best, vocab, args, stale, ema)
        # final.pt — веса для прогноза на последнем шаге (усреднённые, если --ema).
        with ema.applied(model) if ema is not None else _nothing():
            save_checkpoint(args.out / "final.pt", model, None, step, best, vocab, args)
    finally:
        log_f.close()
        del it, loader  # гасит процессы DataLoader между испытаниями Optuna
    print(f"готово: шаг {step}, лучшая вал. потеря {best:.4f}, {args.out}")
    return best


if __name__ == "__main__":  # обязательно для Windows: процессы DataLoader запускаются через spawn
    main()

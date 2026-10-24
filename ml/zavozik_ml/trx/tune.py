"""Подбор гиперпараметров TrxGPT через Optuna (TPE + Hyperband-обрезка слабых испытаний).

Каждое испытание — обычный `train.run()` с предложенными параметрами и
одинаковым бюджетом: предобучение — фиксированное число операций
(--trial-tokens), дообучение — фиксированное число шагов (--trial-steps).
Валидационная потеря сообщается Optuna на каждой проверке; испытания хуже
остальных на той же отметке обрываются, не доучиваясь.

    # предобучение: архитектура и оптимизатор на MBD
    python -m zavozik_ml.trx.tune pretrain --out runs/tune-pretrain --trials 24 --hours 6 \\
        --trial-tokens 1.5e8 -- --data /mnt/d/mbd/shards/part_0 --val /mnt/d/mbd/shards/part_5 --workers 6

    # дообучение: регуляризация на компаниях разработки (аудит не трогаем)
    python -m zavozik_ml.trx.tune finetune --out runs/tune-finetune --trials 40 --hours 3 \\
        --replay /mnt/d/mbd/shards/part_0 -- --init runs/pretrain/best.pt \\
        --data "data/trx/case:development[0-80]:2026-06-30" --val "data/trx/case:development[80-100]:2026-06-30"

После `--` — обычные аргументы train.py (данные, val, workers). Исследование
хранится в `<out>/study.db` (SQLite): после выключения ПК тот же вызов
продолжает с того же места, оборванное испытание повторяется. Результат —
`<out>/best_args.txt` (флаги для train.py) и `<out>/best.json`.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
import sys
import time
from pathlib import Path

import optuna
import torch

from .train import build_parser, run

# Флаги train.py, которые подбираются; в best_args.txt попадают только они.
TUNED = ("d_model", "layers", "heads", "d_ff", "dropout", "batch", "lr", "weight_decay", "warmup_frac",
         "layer_decay", "ema", "aug_scale", "aug_drop")


def suggest_pretrain(trial: optuna.Trial, a) -> None:
    a.d_model = trial.suggest_categorical("d_model", [256, 384, 512])
    a.layers = trial.suggest_categorical("layers", [4, 6, 8, 10])
    a.heads = a.d_model // 64  # голова внимания — 64 измерения
    a.d_ff = a.d_model * trial.suggest_categorical("ff_mult", [2, 4])
    a.dropout = trial.suggest_float("dropout", 0.0, 0.15)
    a.batch = trial.suggest_categorical("batch", [32, 64])
    a.lr = trial.suggest_float("lr", 1e-4, 3e-3, log=True)
    a.weight_decay = trial.suggest_float("weight_decay", 0.01, 0.3, log=True)
    a.warmup_frac = trial.suggest_float("warmup_frac", 0.01, 0.1)


def suggest_finetune(trial: optuna.Trial, a, replay: str | None) -> None:
    a.lr = trial.suggest_float("lr", 1e-5, 5e-4, log=True)
    a.dropout = trial.suggest_float("dropout", 0.05, 0.35)
    a.weight_decay = trial.suggest_float("weight_decay", 0.01, 0.5, log=True)
    a.layer_decay = trial.suggest_float("layer_decay", 0.5, 1.0)
    a.ema = trial.suggest_categorical("ema", [0.0, 0.99, 0.998])
    a.aug_scale = trial.suggest_float("aug_scale", 0.0, 0.8)
    a.aug_drop = trial.suggest_float("aug_drop", 0.0, 0.25)
    a.warmup_frac = trial.suggest_float("warmup_frac", 0.02, 0.15)
    if replay:
        # Доля окон MBD в батче — «повторение» предобучения против забывания и переобучения.
        w = trial.suggest_float("replay", 0.0, 1.0)
        if w > 0.02:
            a.data = list(a.data) + [f"{replay}:::{w:.3f}"]


def flags(a, stage: str, base_data: list[str]) -> str:
    parts = []
    for d in a.data[len(base_data):]:  # подмешанный MBD — тоже часть рецепта
        parts += ["--data", d]
    for k in TUNED:
        if stage == "finetune" and k in ("d_model", "layers", "heads", "d_ff", "batch"):
            continue  # архитектура — от предобученной модели
        parts += [f"--{k.replace('_', '-')}", str(getattr(a, k))]
    return " ".join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["pretrain", "finetune"])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--trials", type=int, default=24, help="сколько испытаний всего (с учётом прошлых запусков)")
    p.add_argument("--hours", type=float, default=0, help="остановиться через N часов (0 — без лимита)")
    p.add_argument("--trial-tokens", type=float, default=1.5e8, help="pretrain: операций на испытание")
    p.add_argument("--trial-steps", type=int, default=3000, help="finetune: шагов на испытание")
    p.add_argument("--evals", type=int, default=8, help="проверок на испытание (точки обрезки)")
    p.add_argument("--replay", default=None, help="finetune: шард MBD для подмешивания")
    p.add_argument("--seed", type=int, default=0)
    argv = sys.argv[1:]
    cut = argv.index("--") if "--" in argv else len(argv)
    a = p.parse_args(argv[:cut])
    train_argv = argv[cut + 1 :]  # после -- : аргументы train.py
    base = build_parser().parse_args(train_argv)
    if not base.data:
        p.error("после -- нужен хотя бы один --data")
    a.out.mkdir(parents=True, exist_ok=True)

    # Пульс испытаний: если ПК выключился посреди испытания, при следующем
    # запуске оно помечается неудачным и повторяется один раз.
    url = f"sqlite:///{a.out.resolve() / 'study.db'}"
    if hasattr(optuna.storages, "RetryHeartbeatStaleTrialCallback"):  # Optuna ≥ 4.9
        storage = optuna.storages.RDBStorage(
            url, heartbeat_interval=60, grace_period=180,
            heartbeat_stale_trial_callback=optuna.storages.RetryHeartbeatStaleTrialCallback(max_retry=1))
    else:
        storage = optuna.storages.RDBStorage(
            url, heartbeat_interval=60, grace_period=180,
            failed_trial_callback=optuna.storages.RetryFailedTrialCallback(max_retry=1))
    study = optuna.create_study(
        study_name=a.stage, storage=storage, direction="minimize", load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=a.seed, multivariate=True, n_startup_trials=6),
        pruner=optuna.pruners.HyperbandPruner(min_resource=2, max_resource=a.evals, reduction_factor=3))
    done = [t for t in study.trials if t.state in (optuna.trial.TrialState.COMPLETE, optuna.trial.TrialState.PRUNED)]
    left = a.trials - len(done)
    print(f"исследование {a.stage}: уже {len(done)} испытаний, осталось {max(left, 0)}", flush=True)

    def objective(trial: optuna.Trial) -> float:
        t = copy.deepcopy(base)
        if a.stage == "pretrain":
            suggest_pretrain(trial, t)
            t.token_budget = a.trial_tokens
            t.max_steps = max(1, int(a.trial_tokens // (t.batch * t.accum * t.seq_len)))
        else:
            suggest_finetune(trial, t, a.replay)
            t.token_budget = 0
            t.max_steps = a.trial_steps
            t.patience = max(t.patience, 3)
        t.eval_every = max(1, t.max_steps // a.evals)
        t.out = a.out / f"trial_{trial.number:03d}"
        if t.out.exists():
            shutil.rmtree(t.out)  # повтор оборванного испытания — с нуля
        t.resume = None
        trial.set_user_attr("flags", flags(t, a.stage, base.data))
        trial.set_user_attr("max_steps", t.max_steps)
        print(f"\n=== испытание {trial.number}: {trial.params}", flush=True)
        t0 = time.time()
        try:
            value = run(t, trial)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            raise optuna.TrialPruned("не влезло в видеопамять")
        except FloatingPointError as e:
            print(f"испытание {trial.number} разошлось: {e}")
            return math.inf
        finally:
            trial.set_user_attr("minutes", round((time.time() - t0) / 60, 1))
            for f in ("last.pt", "final.pt"):  # оптимизатор не нужен; best.pt — только у лучшего
                (t.out / f).unlink(missing_ok=True)
        return value

    def keep_best(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        try:
            best = study.best_trial
        except ValueError:
            return
        for d in a.out.glob("trial_*"):
            if d.name != f"trial_{best.number:03d}":
                (d / "best.pt").unlink(missing_ok=True)
        info = {"value": best.value, "trial": best.number, "params": best.params, **best.user_attrs,
                "checkpoint": str(a.out / f"trial_{best.number:03d}" / "best.pt")}
        (a.out / "best.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
        (a.out / "best_args.txt").write_text(best.user_attrs["flags"] + "\n")
        print(f"лучшее пока: испытание {best.number}, вал. {best.value:.4f} | {best.user_attrs['flags']}", flush=True)

    if left > 0:
        study.optimize(objective, n_trials=left, timeout=a.hours * 3600 or None, callbacks=[keep_best],
                       gc_after_trial=True, catch=(Exception,))  # сбой одного испытания не рушит ночной подбор
    keep_best(study, None)
    states = {}
    for t in study.trials:
        states[t.state.name] = states.get(t.state.name, 0) + 1
    print(f"итог: {states}; лучшие флаги в {a.out / 'best_args.txt'}")
    print("важность параметров:", {k: round(v, 3) for k, v in _importance(study).items()})


def _importance(study: optuna.Study) -> dict[str, float]:
    try:
        return optuna.importance.get_param_importances(study)
    except Exception:  # мало завершённых испытаний
        return {}


if __name__ == "__main__":
    main()

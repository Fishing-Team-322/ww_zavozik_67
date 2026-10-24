"""Валидационная потеря готовой модели на заданных окнах — чтобы сравнить две
контрольные точки на одних и тех же данных (например, старое и новое предобучение).

    python -m zavozik_ml.trx.score runs/pretrain/best.pt runs/pretrain-v2/best.pt \\
        --val /mnt/d/mbd/shards/part_5 --val-windows 1024

Последней строкой печатает путь лучшей модели.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch

from .dataset import build_vocab, validation_windows
from .train import evaluate, load_model, parse_source, pick_device


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("models", type=Path, nargs="+")
    p.add_argument("--val", action="append", required=True)
    p.add_argument("--seq-len", type=int, default=512)
    p.add_argument("--val-windows", type=int, default=1024)
    p.add_argument("--min-len", type=int, default=16)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--device", default="auto")
    a = p.parse_args()
    device = pick_device(a.device)
    amp = torch.bfloat16 if device.type == "cuda" and torch.cuda.is_bf16_supported() else None
    scores = {}
    for path in a.models:
        if not path.exists():
            print(f"{path}: нет файла")
            continue
        model, vocab, _ = load_model(path)
        sources = [parse_source(s) for s in a.val]
        if len(build_vocab(sources, base=vocab)) > len(vocab):
            print(f"{path}: в данных есть типы, которых модель не знает — пропуск")
            continue
        model.to(device)
        windows = validation_windows(sources, min(a.seq_len, model.cfg.max_len), a.val_windows, a.min_len)
        v = evaluate(model, windows, device, amp, a.batch)
        scores[path] = v["loss"]
        print(f"{path}: вал. потеря {v['loss']:.4f} (дни {v['delta']:.3f}, тип {v['type']:.3f}, сумма {v['amount']:.3f}), "
              f"параметров {model.n_params() / 1e6:.1f} млн", flush=True)
        del model
    if not scores:
        raise SystemExit("ни одной модели не оценено")
    print(min(scores, key=scores.get))


if __name__ == "__main__":
    main()

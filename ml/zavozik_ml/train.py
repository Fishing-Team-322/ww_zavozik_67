"""Обучение глобальных моделей на всех данных для прода.

    python -m zavozik_ml.train                       # все глобальные модели
    python -m zavozik_ml.train --models gbm_global

Артефакты пишутся в ml/artifacts/<model>/ и подхватываются gRPC-сервером
при старте (ML_ARTIFACTS). Качество проверяем отдельно бэктестом —
здесь модель видит все компании и весь период.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from zavozik_ml import forecasters
from zavozik_ml.data import DEFAULT_FLOWS, load_companies
from zavozik_ml.forecasters import models  # noqa: F401
from zavozik_ml.serving.server import DEFAULT_ARTIFACTS
from zavozik_ml.provenance import source_fingerprint


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--models", default=",".join(m.name for m in forecasters.all_models() if m.is_global))
    p.add_argument("--flows", type=Path, default=DEFAULT_FLOWS)
    p.add_argument("--out", type=Path, default=DEFAULT_ARTIFACTS)
    args = p.parse_args()

    companies = load_companies(args.flows)
    histories = [c.history for c in companies]
    source_hash = source_fingerprint()
    for name in args.models.split(","):
        model = forecasters.get(name)
        if not model.is_global:
            print(f"{name}: not a global model, nothing to train")
            continue
        t0 = time.perf_counter()
        model.fit(histories)
        model.save(args.out / name)
        info = {
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "companies": len(histories),
            "last_date": str(max(h.dates[-1] for h in histories)),
            "flows": str(args.flows.name),
            "flows_sha256": hashlib.sha256(args.flows.read_bytes()).hexdigest(),
            "source_sha256_at_start": source_hash,
            "source_changed_during_run": source_hash != source_fingerprint(),
            "flow_scope": "business_without_internal_transfers_including_recurring",
            "evaluation": "production fit on all companies; do not evaluate holdout quality with this artifact",
        }
        (args.out / name / "train_info.json").write_text(json.dumps(info, indent=1))
        print(f"{name}: trained on {len(histories)} companies in {time.perf_counter() - t0:.0f}s -> {args.out / name}")


if __name__ == "__main__":
    main()

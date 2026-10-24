"""Internal generalization test: entire normalized payment templates held out.

Synthetic examples with an exact held-out normalized purpose are removed too.
This is stricter than company splitting but still uses weak labels from the
same previously inspected source. It is not an external gold-standard test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import numpy as np

from . import evaluate, labels
from .model import Classifier
from .text import normalize
from .train import ML_DIR, REPO, real_rows, train_model
from zavozik_ml.provenance import source_fingerprint


def split_templates(df, seed=20261024):
    keys = df.direction + "|" + df.payment_purpose.map(normalize)
    # One whole key stays in one split even if weak labels disagree.
    groups = df.assign(template=keys).groupby("template").label.agg(lambda s: s.mode().iloc[0])
    rng = random.Random(seed)
    calibration, test = set(), set()
    for label in sorted(groups.unique()):
        pool = sorted(groups[groups == label].index)
        rng.shuffle(pool)
        n = int(len(pool)*.2)
        test.update(pool[:n])
        calibration.update(pool[n:2*n])
    return keys, calibration, test


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=REPO/"cashflow_dataset_participants/all_operations.csv")
    ap.add_argument("--out", type=Path, default=ML_DIR/"data/classifier_template_audit")
    ap.add_argument("--report", type=Path, default=ML_DIR/"reports/classifier_templates.md")
    ap.add_argument("--seed", type=int, default=20261024)
    args = ap.parse_args()
    source = source_fingerprint()
    df = labels.load_dataset(args.data)
    go = labels.go_rule_labels(args.data, REPO, ML_DIR/"data/rule_labels.csv")
    keys, calibration, test = split_templates(labels.teacher_labels(df, go), args.seed)
    train_templates = keys[~keys.isin(calibration|test)].nunique()
    parts = labels.teacher_label_partitions({"train": df[~keys.isin(calibration|test)],
        "calibration": df[keys.isin(calibration)], "test": df[keys.isin(test)]}, go)
    tr, ca, te = parts["train"], parts["calibration"], parts["test"]
    print(f"templates train={train_templates} calibration={len(calibration)} test={len(test)}; "
          f"operations {len(tr)}/{len(ca)}/{len(te)}", flush=True)
    clf = train_model(real_rows(tr), args.seed, 60000, 1500, 3e-6,
                      dev_rows=real_rows(ca), excluded_purposes=calibration|test)
    clf.meta.update(evaluation_only=True, protocol="normalized_purpose_holdout", seed=args.seed)
    clf.save(args.out)
    clf = Classifier.load(args.out)
    rows = real_rows(te)
    model, conf = evaluate.predict_rows(clf, rows)
    blinded, blind_conf = evaluate.predict_rows(clf, [dict(r, name="", inn="") for r in rows])
    hybrid = evaluate.hybrid_predictions(te.rule, model, conf)
    stats = {name: evaluate.scores(te.label, pred, te.amount) for name, pred in
             [("rules", te.rule), ("model", model), ("hybrid", hybrid), ("model_without_counterparty", blinded)]}
    stats["confidence"] = evaluate.confidence_metrics(te.label, model, conf)
    stats["protocol"] = {"seed": args.seed, "train_templates": int(train_templates), "weak_label_scope": "partition_only",
        "calibration_templates": sorted(calibration), "test_templates": sorted(test),
        "source_sha256": source, "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "source_changed_during_run": source != source_fingerprint(), "temperature": clf.temperature}
    def cast(value):
        return value.item() if isinstance(value, np.generic) else value
    (args.out/"metrics.json").write_text(json.dumps(stats, default=cast, ensure_ascii=False, indent=2))
    table = evaluate._md_table(["Способ", "N", "Accuracy", "Macro F1", "По обороту"],
        [[name, s["n"], evaluate._pct(s["accuracy"]), f"{s['macro_f1']:.3f}", evaluate._pct(s["turnover_accuracy"])]
         for name, s in stats.items() if name not in ("confidence", "protocol")])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(f"""# Обобщение классификатора на новые шаблоны

Шаблон = направление + нормализованное назначение (без дат, сумм и номеров).
Целые шаблоны разделены 60/20/20 внутри категорий: {train_templates} обучение,
{len(calibration)} калибровка, {len(test)} тест. Seed {args.seed}.
Точные совпадения с calibration/test удалены также из обучающей аугментации.
Температура калибрована только по calibration, оценка выполнена после save/load артефакта.
Метки пустых назначений по контрагентам строятся отдельно внутри каждой группы.

{table}

Это **внутренний тест на слабых метках** того же синтетического генератора.
Он проверяет более строгий сдвиг формулировок, чем разбиение по компаниям,
но похожие семантические шаблоны и известные контрагенты могут остаться в обучении.
Последняя строка дополнительно убирает имя и ИНН контрагента на входе.
Словари аугментации составлены вручную и не являются независимым источником разметки.

ECE уверенности: {stats['confidence']['ece']:.4f}; уверенных ошибок (≥0.8):
{stats['confidence']['confident_errors']}. Не настраивать параметры по этому отчёту.

Код на старте: `{source}`. Метрики/протокол: `data/classifier_template_audit/metrics.json`.
""")
    print(table, flush=True)


if __name__ == "__main__":
    main()

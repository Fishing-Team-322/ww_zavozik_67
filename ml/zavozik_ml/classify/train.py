"""Обучение классификатора категорий операций.

    cd ml && PYTHONPATH=gen:. python -m zavozik_ml.classify.train \\
        --data ../cashflow_dataset_participants/all_operations.csv

Шаги:
1. Метки: правила Go (backend/cmd/rulelabel) + ручная доразметка шаблонов
   (labels.py) — «учитель».
2. Оценка как на чужих данных: 20% компаний отложены целиком, модель
   обучается на остальных (+ аугментация) и сравнивается с правилами Go
   на отложенных и на вручную составленном novel_test.csv.
3. Финальная модель — на всех компаниях, тот же рецепт → ml/artifacts/classifier.
4. Отчёт ml/reports/classifier.md (evaluate.write_report).

Нужен Go (метки правил считает тот же код, что в проде) и scipy (есть
в зависимостях statsmodels); в сервинге нужен только numpy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import minimize

from . import augment, evaluate, labels
from .model import DEFAULT_DIR, Classifier
from .text import CATEGORIES, N_FEATURES, Op, cache_key, counterparty_type, features, normalize

ML_DIR = Path(__file__).resolve().parents[2]
REPO = ML_DIR.parent
CAT_INDEX = {c: i for i, c in enumerate(CATEGORIES)}
FAKE_INN = {"org": "0000000000", "person": "000000000000", "none": "", "bad": "0"}


def to_op(r: dict) -> Op:
    inn = r.get("inn")
    if inn is None:
        inn = FAKE_INN.get(r.get("inn_type", "none"), "")
    return Op(direction=r["direction"], purpose=r.get("purpose") or "", counterparty_name=r.get("name") or "",
              counterparty_inn=inn, amount=float(r.get("amount") or 0.0))


def real_rows(df: pd.DataFrame) -> list[dict]:
    return [dict(direction=d, purpose=p, name=n, inn=i, inn_type=counterparty_type(i), amount=a, label=l, company=c)
            for d, p, n, i, a, l, c in zip(df.direction, df.payment_purpose, df.counterparty_name, df.counterparty_inn,
                                           df.amount, df.label, df.company_id)]


def dedupe(rows: list[dict]) -> list[dict]:
    """Одинаковые по признакам операции → одна строка с весом 1 + ln(n)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[cache_key(to_op(r))].append(r)
    out = []
    for g in groups.values():
        lab = Counter(r["label"] for r in g).most_common(1)[0][0]
        r = dict(g[0], label=lab, weight=1.0 + math.log(len(g)))
        out.append(r)
    return out


def counterparty_dropout(rows: list[dict], seed: int, rate: float = .25) -> list[dict]:
    """Avoid learning that an absent name/INN always implies `other`.

    Keep original examples and add a fixed random fraction of views without
    counterparty fields. An empty purpose needs the name for its label, so
    those rows cannot retain their category after removing the counterparty.
    """
    if not 0 <= rate <= 1:
        raise ValueError("counterparty dropout rate must be in [0, 1]")
    rng = random.Random(seed + 20261024)
    added = [dict(r, name="", inn="", inn_type="none") for r in rows
             if normalize(r.get("purpose", "")) and rng.random() < rate]
    return rows + added


def build_training(rows_real: list[dict], seed: int, n_perturb: int, n_synth: int,
                   name_dropout: float = .25) -> list[dict]:
    rng = random.Random(seed)
    uniq = dedupe(rows_real)
    pert = [dict(augment.perturb(rng.choice(uniq), rng), weight=1.0) for _ in range(n_perturb)]
    syn = [dict(r, weight=1.0) for r in augment.synth(rng, n_synth)]
    return counterparty_dropout(uniq + pert + syn, seed, name_dropout)


def matrix(rows: list[dict]) -> sparse.csr_matrix:
    indptr, indices, data = [0], [], []
    for r in rows:
        idx, val = features(to_op(r))
        indices.extend(idx)
        data.extend(val)
        indptr.append(len(indices))
    return sparse.csr_matrix((np.asarray(data, np.float32), np.asarray(indices, np.int32), np.asarray(indptr)),
                             shape=(len(rows), N_FEATURES))


def fit_softmax(X: sparse.csr_matrix, y: np.ndarray, w: np.ndarray, l2: float, maxiter: int = 300):
    """Мультиномиальная логрегрессия с L2, L-BFGS. Обучаем только на столбцах,
    которые встречаются в данных (остальные веса = 0)."""
    used = np.unique(X.indices)
    Xu = X[:, used].tocsr()
    n, d = Xu.shape
    k = len(CATEGORIES)
    Y = np.zeros((n, k), dtype=np.float64)
    Y[np.arange(n), y] = 1.0
    w = w / w.sum()
    XT = Xu.T.tocsr()

    def f(theta):
        Wm = theta[: d * k].reshape(d, k)
        b = theta[d * k:]
        Z = Xu @ Wm + b
        Z -= Z.max(axis=1, keepdims=True)
        logsum = np.log(np.exp(Z).sum(axis=1, keepdims=True))
        logp = Z - logsum
        loss = -(w * (Y * logp).sum(axis=1)).sum() + 0.5 * l2 * (Wm * Wm).sum()
        G = (np.exp(logp) - Y) * w[:, None]
        gW = XT @ G + l2 * Wm
        gb = G.sum(axis=0)
        return loss, np.concatenate([gW.ravel(), gb])

    theta0 = np.zeros(d * k + k)
    res = minimize(f, theta0, jac=True, method="L-BFGS-B", options=dict(maxiter=maxiter))
    W = np.zeros((N_FEATURES, k), dtype=np.float32)
    W[used] = res.x[: d * k].reshape(d, k)
    return W, res.x[d * k:].astype(np.float32), res


def class_weights(rows: list[dict]) -> np.ndarray:
    tot = Counter()
    for r in rows:
        tot[r["label"]] += r["weight"]
    mean = sum(tot.values()) / len(tot)
    # Редкие категории подтягиваем (−0.5 степень), но не уравниваем полностью.
    return np.array([r["weight"] * (mean / tot[r["label"]]) ** 0.5 for r in rows])


def fit_temperature(logits: np.ndarray, y: np.ndarray) -> float:
    best, best_t = float("inf"), 1.0
    for t in np.exp(np.linspace(np.log(0.3), np.log(5.0), 60)):
        z = logits / t
        z = z - z.max(axis=1, keepdims=True)
        nll = -(z[np.arange(len(y)), y] - np.log(np.exp(z).sum(axis=1))).mean()
        if nll < best:
            best, best_t = nll, float(t)
    return best_t


def train_model(rows_real: list[dict], seed: int, n_perturb: int, n_synth: int, l2: float,
                dev_rows: list[dict] | None = None, log=print, excluded_purposes: set[str] | None = None,
                name_dropout: float = .25) -> Classifier:
    t0 = time.time()
    rows = build_training(rows_real, seed, n_perturb, n_synth, name_dropout=name_dropout)
    if excluded_purposes:
        rows = [r for r in rows if r["direction"] + "|" + normalize(r.get("purpose", "")) not in excluded_purposes]
    X = matrix(rows)
    y = np.array([CAT_INDEX[r["label"]] for r in rows])
    w = class_weights(rows)
    log(f"  обучающих строк {len(rows)}, признаков {len(np.unique(X.indices))}, {time.time() - t0:.0f} c")
    W, b, res = fit_softmax(X, y, w, l2)
    log(f"  L-BFGS: {res.nit} итераций, loss {res.fun:.4f}, {time.time() - t0:.0f} c")
    clf = Classifier(W, b)
    if dev_rows:
        yd = np.array([CAT_INDEX[r["label"]] for r in dev_rows])
        clf.temperature = fit_temperature(clf.logits([to_op(r) for r in dev_rows]), yd)
        log(f"  температура {clf.temperature:.2f}")
    return clf


def dev_set(rows_real: list[dict], seed: int, n: int, name_dropout: float = .25) -> list[dict]:
    """Зашумлённые операции отложенных компаний + свежая синтетика (другое зерно) —
    для температуры; порог фиксирован, novel_test.csv здесь не участвует."""
    rng = random.Random(seed + 1000)
    uniq = dedupe(rows_real)
    rows = [augment.perturb(rng.choice(uniq), rng) for _ in range(n)] + augment.synth(rng, max(n // 60, 20))
    return counterparty_dropout(rows, seed+1, name_dropout)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=REPO / "cashflow_dataset_participants" / "all_operations.csv")
    ap.add_argument("--rule-labels", type=Path, default=ML_DIR / "data" / "rule_labels.csv",
                    help="кэш меток правил Go (пересчитывается, если старше датасета)")
    ap.add_argument("--out", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--report", type=Path, default=ML_DIR / "reports" / "classifier.md")
    ap.add_argument("--holdout", type=float, default=0.2, help="доля компаний в отложенной выборке")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--perturb", type=int, default=60000, help="зашумлённых копий реальных операций")
    ap.add_argument("--synth", type=int, default=1500, help="синтетических перефразировок на категорию")
    ap.add_argument("--l2", type=float, default=3e-6)
    ap.add_argument("--name-dropout", type=float, default=.25, help="доля дополнительных примеров без контрагента")
    ap.add_argument("--min-confidence", type=float, default=0.3)
    ap.add_argument("--no-final", action="store_true", help="только оценка, без финальной модели")
    ap.add_argument("--ablation", action="store_true", help="ещё обучить без словаря и без аугментации (для отчёта)")
    args = ap.parse_args()
    if not 0 < args.holdout < .7 or not 0 <= args.min_confidence <= 1 or not 0 <= args.name_dropout <= 1:
        ap.error("holdout must be in (0, .7); min-confidence and name-dropout must be in [0, 1]")

    print("метки: правила Go + доразметка")
    df = labels.load_dataset(args.data)
    go = labels.go_rule_labels(args.data, REPO, args.rule_labels)
    companies = sorted(df.company_id.unique())
    rng = random.Random(args.seed)
    hold = set(rng.sample(companies, max(1, int(len(companies) * args.holdout))))
    remaining = sorted(set(companies)-hold)
    calibration_ids = set(rng.sample(remaining, max(1, int(len(companies)*.2))))
    parts = labels.teacher_label_partitions({
        "train": df[~df.company_id.isin(hold | calibration_ids)],
        "calibration": df[df.company_id.isin(calibration_ids)],
        "test": df[df.company_id.isin(hold)],
    }, go)
    tr_df, cal_df, ho_df = parts["train"], parts["calibration"], parts["test"]
    print(f"компаний: обучение {tr_df.company_id.nunique()}, калибровка {len(calibration_ids)}, тест {len(hold)} ({len(ho_df)} операций)")

    print("модель для оценки (без отложенных компаний)")
    tr_rows, ho_rows = real_rows(tr_df), real_rows(ho_df)
    # Температура не должна подбираться на тех же компаниях, что final holdout.
    dev = dev_set(real_rows(cal_df), args.seed, 6000, name_dropout=args.name_dropout)
    clf = train_model(tr_rows, args.seed, args.perturb, args.synth, args.l2, dev_rows=dev, name_dropout=args.name_dropout)
    clf.min_confidence = args.min_confidence
    # Preserve the evaluation model separately from the all-company artifact.
    eval_dir = ML_DIR / "data" / "classifier_evaluation"
    clf.meta.update(train_companies=sorted(set(companies)-hold-calibration_ids),
                    calibration_companies=sorted(calibration_ids), test_companies=sorted(hold),
                    evaluation_only=True, weak_label_scope="partition_only", name_dropout=args.name_dropout)
    clf.save(eval_dir)
    clf = Classifier.load(eval_dir)  # evaluate exactly the quantized artifact used by serving
    results = evaluate.evaluate_all(clf, ho_df, ho_rows, dev, REPO)
    if args.ablation:
        results["ablation"] = {}
        for name, n_p, n_s in (("без словаря перефразировок (только шум реальных)", args.perturb, 0),
                               ("без аугментации (только датасет)", 0, 0)):
            print(f"абляция: {name}")
            a = train_model(tr_rows, args.seed, n_p, n_s, args.l2, dev_rows=dev, name_dropout=args.name_dropout if n_p or n_s else 0)
            a.min_confidence = args.min_confidence
            results["ablation"][name] = evaluate.novel(a, REPO)

    if not args.no_final:
        print("финальная модель (все компании)")
        all_rows = real_rows(labels.teacher_labels(df, go))
        final = train_model(all_rows, args.seed, args.perturb, args.synth, args.l2, name_dropout=args.name_dropout)
        # Перенос калибровки с отдельной calibration-группы. Качество финального
        # артефакта на исходных компаниях не объявляется тестовым результатом.
        final.temperature = clf.temperature
        final.min_confidence = args.min_confidence
        final.meta = dict(trained_at=time.strftime("%Y-%m-%d"), n_operations=len(df), l2=args.l2,
                          perturb=args.perturb, synth=args.synth, seed=args.seed, name_dropout=args.name_dropout,
                          holdout_eval={k: results[k]["summary"] for k in ("holdout", "novel")})
        final.meta.update(calibration_companies=sorted(calibration_ids), test_companies=sorted(hold),
                          evaluation_protocol="company_train_calibration_test_60_20_20",
                          weak_label_scope="partition_only_for_evaluation_all_companies_for_final_fit",
                          source_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
                          novel_usage="regression_set_previously_inspected_not_external_test")
        final.save(args.out)
        size = sum(p.stat().st_size for p in args.out.iterdir())
        print(f"артефакт {args.out} ({size / 1e6:.1f} МБ)")
        results["final_novel"] = evaluate.novel(Classifier.load(args.out), REPO)
    # Metrics and row-level regression errors survive subsequent report changes.
    for name in ("novel", "final_novel"):
        if name in results:
            results[name]["df"].to_csv(eval_dir / f"{name}.csv", index=False)
    def serializable(value):
        if isinstance(value, pd.DataFrame):
            return value.to_dict(orient="records")
        if isinstance(value, dict):
            return {str(k): serializable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [serializable(v) for v in value]
        if isinstance(value, np.generic):
            return value.item()
        return value
    (eval_dir / "evaluation.json").write_text(json.dumps(serializable(results), ensure_ascii=False, indent=2))
    evaluate.write_report(results, args, args.report)
    print(f"отчёт {args.report}")


if __name__ == "__main__":
    main()

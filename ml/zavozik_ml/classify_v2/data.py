"""Company AND template-family isolated weak labels for v2."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random

import numpy as np

from .model import sha256_file
from .taxonomy import Taxonomy
from .text import Operation, dedupe_key, encoder_text
from .weak_labels import annotate
from .splitting import TemplateRegistry, PROTOCOL, audit, digest, isolate, template_text

ML_DIR = Path(__file__).resolve().parents[2]
REPO = ML_DIR.parent


def operation(row: dict) -> Operation:
    return Operation(row["direction"], row.get("purpose", ""), row.get("name", ""),
                     row.get("inn_type", "none"), float(row.get("amount", 0)), row.get("id", ""))


def real_rows(df) -> list[dict]:
    from zavozik_ml.classify.text import counterparty_type
    return [dict(id=oid, company=company, direction=d, purpose=p, name=n,
                 inn_type=counterparty_type(inn), amount=float(a), label=category, source="case_weak")
            for oid, company, d, p, n, inn, a, category in zip(
                df.operation_id, df.company_id, df.direction, df.payment_purpose,
                df.counterparty_name, df.counterparty_inn, df.amount, df.label)]


def load_partitions(source: Path, split: Path, rule_cache: Path, seed: int = 42):
    from zavozik_ml.classify import labels
    spec = json.loads(split.read_text())
    cal = set(spec["calibration_companies"])
    test = set(spec["test_companies"])
    if cal & test:
        raise ValueError("calibration and test companies overlap")
    df = labels.load_dataset(source)
    if df.direction.isna().any() or not np.isfinite(df.amount).all() or (df.amount < 0).any():
        raise ValueError("invalid source operation direction/amount")
    companies = set(df.company_id)
    if not cal <= companies or not test <= companies:
        raise ValueError("split references missing companies")
    go = labels.go_rule_labels(source, REPO, rule_cache)
    subsets = {"train": df[~df.company_id.isin(cal | test)],
               "calibration": df[df.company_id.isin(cal)], "test": df[df.company_id.isin(test)]}
    # Provisional weak labels are used for split stratification only. Missing-
    # purpose majority labels MUST be recomputed on the retained rows below.
    provisional = labels.teacher_label_partitions(subsets, go)
    retained, registry, split_audit = isolate({k: real_rows(v) for k, v in provisional.items()}, seed)
    ids = {k: {r["id"] for r in rows} for k, rows in retained.items()}
    filtered = {k: part[part.operation_id.isin(ids[k])].copy() for k, part in subsets.items()}
    final = labels.teacher_label_partitions(filtered, go)
    parts = {}
    for name, frame in final.items():
        lineage = {r["id"]: r for r in retained[name]}
        parts[name] = [dict(r, **{key: lineage[r["id"]][key] for key in
                                 ("template_family", "parent_id", "parent_company")}) for r in real_rows(frame)]
    return parts, {
        "source_sha256": sha256_file(source), "split_sha256": sha256_file(split),
        "train_companies": sorted(companies - cal - test), "calibration_companies": sorted(cal),
        "test_companies": sorted(test), "weak_label_scope": "partition_only_not_human_gold",
        "split_protocol": PROTOCOL, "template_purging": split_audit,
        "statistical_teacher_labels": "recomputed within retained partition after template purging",
    }, registry


def dedupe(rows: list[dict], max_variants: int = 2) -> list[dict]:
    """One purpose template has bounded name/amount views, not 1000 repeats.

    Conflicting categories remain separate supervised targets; no majority is
    taken from another split. 1+log(count) weights are capped to avoid allowing
    one ubiquitous template to dominate all rare economic categories.
    """
    groups = defaultdict(list)
    for row in rows:
        groups[(dedupe_key(operation(row)), row["label"])].append(row)
    result = []
    for key in sorted(groups):
        g = groups[key]
        g = sorted(g, key=lambda r: (encoder_text(operation(r)), r.get("id", "")))
        selected = [g[0]]
        if max_variants > 1 and len(g) > 1 and encoder_text(operation(g[-1])) != encoder_text(operation(g[0])):
            selected.append(g[-1])
        for r in selected:
            result.append(dict(r, weight=min(3.0, 1 + math.log(len(g))) / len(selected), template_count=len(g)))
    return result


def enrich(rows: list[dict], taxonomy: Taxonomy) -> list[dict]:
    result = []
    for r in rows:
        if r["label"] not in taxonomy.categories:
            continue
        op = operation(r)
        weak = annotate(op, taxonomy)
        result.append(dict(r, text=encoder_text(op), channel=weak.channel, tags=list(weak.tags),
                           auxiliary_label_source=weak.source))
    return result


def training_rows(rows: list[dict], taxonomy: Taxonomy, seed: int = 42,
                  perturb: int = 24000, synth: int = 1000, dropout: float = .25,
                  registry: TemplateRegistry | None = None) -> list[dict]:
    from zavozik_ml.classify import augment
    rng = random.Random(seed)
    if registry is None or not rows:
        raise ValueError("training requires nonempty template-isolated parents and a registry")
    unique = dedupe(rows)
    # Existing v1 perturbations/synthetic dictionaries are reused verbatim.
    # Only train-company examples can be sampled here.
    noisy = [dict(augment.perturb(rng.choice(unique), rng), weight=1, source="train_perturb", company="")
             for _ in range(perturb)]
    synthetic = [dict(r, weight=1, source="v1_synth", company="", parent_company="",
                      parent_id=f"synthetic-{i}", template_family="synthetic-" + digest(template_text(r["purpose"]))[:20])
                 for i, r in enumerate(augment.synth(rng, synth))]
    combined = [r for r in unique + noisy + synthetic if registry.training_safe(r)]
    extra = []
    for r in combined:
        if r.get("purpose", "").strip() and rng.random() < dropout:
            extra.append(dict(r, name="", inn_type="none", source="counterparty_dropout", weight=1))
    # Known calendar/contract semantics need both literal words and noisy views.
    # The clean base rows are retained when augmented text loses a weak marker.
    return enrich(combined + extra, taxonomy)


def calibration_views(rows: list[dict], taxonomy: Taxonomy) -> list[dict]:
    # Primary model/temperature selection uses real observations only. Noise
    # belongs to an explicitly separate robustness study, never this score.
    return enrich(dedupe(rows), taxonomy)


def write_rows(path: Path, rows: list[dict]):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare(source: Path, out: Path, split: Path, rule_cache: Path, seed=42, perturb=24000, synth=1000):
    if out.exists():
        raise ValueError("prepared output already exists; never overwrite a frozen split")
    out.mkdir(parents=True)
    taxonomy = Taxonomy.load()
    parts, meta, registry = load_partitions(source, split, rule_cache, seed)
    train = training_rows(parts["train"], taxonomy, seed, perturb, synth, registry=registry)
    cal = calibration_views(parts["calibration"], taxonomy)
    records = {"train": train, "calibration": cal,
               "calibration_full": enrich(parts["calibration"], taxonomy),
               "test": enrich(parts["test"], taxonomy)}
    checks = audit(records, registry)
    registry_path = out / "template_registry.json"
    registry_path.write_text(json.dumps(registry.document(), ensure_ascii=False, sort_keys=True) + "\n")
    (out / "split_audit.json").write_text(json.dumps(checks, indent=2) + "\n")
    meta.update(seed=seed, perturb=perturb, synth_per_category=synth, taxonomy_sha256=taxonomy.sha256,
                description="Company and template-family disjoint, augmented train only; statistical labels inferred after purging",
                template_registry_sha256=sha256_file(registry_path), split_audit=checks,
                split_audit_sha256=sha256_file(out / "split_audit.json"),
                train_real_parents=len(parts["train"]), train_real_families=len({r["template_family"] for r in parts["train"]}))
    prep_files = [Path(__file__).with_name(name) for name in ("data.py", "splitting.py", "text.py", "weak_labels.py", "taxonomy.py", "taxonomy.json")]
    prep_files += [ML_DIR / "zavozik_ml/classify" / name for name in ("labels.py", "augment.py", "text.py")]
    meta["preparation_files_sha256"] = {str(p.relative_to(ML_DIR)): sha256_file(p) for p in prep_files}
    for name, rows in records.items():
        path = out / f"{name}.jsonl"
        write_rows(path, rows)
        meta[name] = {"rows": len(rows), "sha256": sha256_file(path),
                      "template_families": len({r["template_family"] for r in rows}),
                      "unique_inputs": len({r["text"] for r in rows}),
                      "categories": dict(Counter(r["label"] for r in rows)),
                      "channels": dict(Counter(r["channel"] for r in rows))}
    (out / "data_manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=REPO / "cashflow_dataset_participants/all_operations.csv")
    p.add_argument("--out", type=Path, default=ML_DIR / "data/classifier_v2/prepared")
    p.add_argument("--split", type=Path, default=ML_DIR / "artifacts/classifier/meta.json")
    p.add_argument("--rule-labels", type=Path, default=ML_DIR / "data/rule_labels.csv")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--perturb", type=int, default=24000)
    p.add_argument("--synth", type=int, default=1000)
    args = p.parse_args()
    m = prepare(args.data, args.out, args.split, args.rule_labels, args.seed, args.perturb, args.synth)
    print(json.dumps({k: v for k, v in m.items() if k.endswith("companies") or k in ("train", "calibration", "test")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

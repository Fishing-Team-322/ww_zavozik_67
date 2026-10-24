"""Real-only corpus reusing the frozen company AND template ownership.

Does not import the supervised data builder, Go rules, category taxonomy or
synthetic augmentation. The inherited ownership was weak-label stratified;
that historical fact is retained explicitly, not disguised as a blind split.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re

from zavozik_ml.classify_v2.splitting import TemplateRegistry, signatures, template_text, structural_text
from zavozik_ml.classify_v2.model import sha256_file

PROTOCOL = "label_free_real_company_template_v1"
TEXT_VERSION = "purpose_only_structural_query_v1"
STOPS = frozenset("оплата платеж перечисление поступление списание назначение указано неизвестно средства средств за по на от и в с из для номер дата мес сумма рублей рублями рубль процент счет счету счета договор договору договора".split())


def semantic_text(purpose: str) -> str:
    value = structural_text(purpose)
    return "" if value == "<uninformative>" else value


def informative(text: str) -> bool:
    return any(w not in STOPS for w in re.findall(r"[а-яa-z]{3,}", text))


def embedding_text(purpose: str) -> str:
    return "query: " + semantic_text(purpose)


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict]):
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def prepare(source: Path, frozen: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError("corpus exists; never overwrite a frozen experiment")
    meta = json.loads((frozen / "data_manifest.json").read_text())
    regpath = frozen / "template_registry.json"
    if sha256_file(source) != meta["source_sha256"] or sha256_file(regpath) != meta["template_registry_sha256"]:
        raise ValueError("source/registry digest mismatch")
    reg = json.loads(regpath.read_text())
    registry = TemplateRegistry(reg["families"], reg["owners"])
    company_sets = {p: set(meta[p + "_companies"]) for p in ("train", "calibration", "test")}
    for a, b in (("train", "calibration"), ("train", "test"), ("calibration", "test")):
        if company_sets[a] & company_sets[b]:
            raise ValueError("company overlap")
    company_owner = {c: p for p, values in company_sets.items() for c in values}
    parts = {p: [] for p in company_sets}
    purged = Counter()
    seen_ids = set()
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            oid, company = row["operation_id"], row["company_id"]
            if oid in seen_ids:
                raise ValueError("duplicate operation id")
            seen_ids.add(oid)
            p = company_owner[company]
            direction = {"Поступление": "in", "Списание": "out"}.get(row["direction"])
            if direction is None:
                raise ValueError("invalid direction")
            family = registry.families[template_text(row["payment_purpose"])]
            if registry.owners[family] != p:
                purged[p] += 1
                continue
            purpose = row["payment_purpose"] or ""
            # Deliberate whitelist: category/channel/tag/teacher/weight never
            # enter the new corpus even if the source adds such columns later.
            parts[p].append(dict(id=oid, company=company, direction=direction,
                                 purpose=purpose, semantic_text=semantic_text(purpose),
                                 text=embedding_text(purpose), template_family=family))
    intersections = {}
    for a, b in (("train", "calibration"), ("train", "test"), ("calibration", "test")):
        checks = {
            "companies": len({r["company"] for r in parts[a]} & {r["company"] for r in parts[b]}),
            "families": len({r["template_family"] for r in parts[a]} & {r["template_family"] for r in parts[b]}),
            "texts": len({r["text"] for r in parts[a]} & {r["text"] for r in parts[b]}),
            "signatures": len({s for r in parts[a] for s in signatures(r["purpose"])} &
                              {s for r in parts[b] for s in signatures(r["purpose"])}),
        }
        if any(checks.values()):
            raise ValueError(f"partition overlap: {a}/{b} {checks}")
        intersections[f"{a}__{b}"] = checks
    out.mkdir(parents=True)
    report = dict(protocol=PROTOCOL, text_version=TEXT_VERSION,
                  source_sha256=sha256_file(source), inherited_manifest_sha256=sha256_file(frozen / "data_manifest.json"),
                  registry_sha256=sha256_file(regpath), intersections=intersections,
                  split_origin="Frozen company_purged_template_families_v3; historical weak-label stratification only",
                  fit_targets="none", synthetic_rows=0, augmented_rows=0,
                  code_sha256=sha256_file(Path(__file__)))
    for p, rows in parts.items():
        write_rows(out / f"{p}.jsonl", rows)
        # One entry per semantic text, with direction retained as a constraint.
        groups = defaultdict(list)
        for r in rows:
            groups[(r["direction"], r["text"])].append(r)
        unique = []
        for key, values in sorted(groups.items()):
            families = {r["template_family"] for r in values}
            if len(families) != 1:
                raise ValueError("one semantic text has multiple template families")
            first = min(values, key=lambda r: r["id"])
            unique.append(dict(first, count=len(values), companies=sorted({r["company"] for r in values}),
                               usable=informative(first["semantic_text"])))
        write_rows(out / f"{p}_unique.jsonl", unique)
        report[p] = dict(rows=len(rows), unique=len(unique), usable_unique=sum(r["usable"] for r in unique),
                         families=len({r["template_family"] for r in rows}), companies=len({r["company"] for r in rows}),
                         purged_rows=purged[p], sha256=sha256_file(out / f"{p}.jsonl"),
                         unique_sha256=sha256_file(out / f"{p}_unique.jsonl"))
    (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--frozen", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.source, a.frozen, a.out), indent=2))


if __name__ == "__main__":
    main()

"""Label-free discovery v2 preparation, with leakage closure BEFORE splitting.

Leakage families are deliberately conservative: they are NOT semantic classes
or density points. The old lexical slot masks are only leakage guards. Company
membership is inherited, family ownership is newly hashed without targets.
Actual truncated token collisions are joined, not merely checked after fitting.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil

from zavozik_ml.classify.text import norm_direction
from zavozik_ml.classify_v2.model import sha256_file
from zavozik_ml.classify_v2.splitting import signatures, TemplateIndex
from .corpus import write_rows
from .normalization import TEXT_VERSION, analyze, content_key

PROTOCOL = "label_free_company_template_token_closure_v2"
PARTS = ("train", "calibration", "test")
PAIRS = (("train", "calibration"), ("train", "test"), ("calibration", "test"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Components:
    def __init__(self):
        self.parent = {}

    def find(self, value):
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def join(self, a, b):
        a, b = sorted((self.find(a), self.find(b)))
        self.parent[b] = a


def owner_for(family, eligible, seed):
    # Weighted rendezvous hashing: only company partitions actually containing
    # the family are eligible. No category labels or semantic quality involved.
    weights = dict(zip(PARTS, (.6, .2, .2)))
    return min(eligible, key=lambda p: -math.log((int(digest(f"{seed}:{family}:{p}"), 16) + 1) /
                                                (2**256 + 1)) / weights[p])


def prepare(source: Path, company_manifest: Path, out: Path, tokenizers: dict, *,
            source_kind: str, seed=42) -> dict:
    """tokenizers: name -> (callable(list[str])->list[list[int]], provenance).

    All tokenizers required by the comparison must be included before training.
    Adding another later requires a new prepared version if it collides.
    """
    if out.exists():
        raise ValueError("refuse overwrite of prepared corpus")
    if source_kind not in ("case_synthetic", "anonymized_bank") or not tokenizers:
        raise ValueError("explicit source kind and at least one pinned tokenizer required")
    meta = json.loads(company_manifest.read_text())
    if sha256_file(source) != meta["source_sha256"]:
        raise ValueError("source digest mismatch")
    companies = {p: set(meta[p + "_companies"]) for p in PARTS}
    if any(companies[a] & companies[b] for a, b in PAIRS):
        raise ValueError("company overlap")
    company_owner = {c: p for p, cs in companies.items() for c in cs}
    raw, seen = [], set()
    views, aliases = {}, {}
    with source.open(encoding="utf-8-sig", newline="") as stream:
        for r in csv.DictReader(stream, delimiter=";"):
            oid, company, purpose = r["operation_id"], r["company_id"], r["payment_purpose"] or ""
            direction = norm_direction(r["direction"])
            if oid in seen or company not in company_owner or direction not in ("in", "out"):
                raise ValueError("duplicate id, unknown company, or invalid direction")
            seen.add(oid)
            if purpose not in views:
                view = analyze(purpose)
                views[purpose] = view
                # Both historical and cleaned aliases close nuisance-induced
                # family splits. These strings never enter encoder inputs.
                aliases[purpose] = signatures(purpose) | signatures(view.semantic_text)
            view = views[purpose]
            raw.append(dict(id=oid, company=company, direction=direction, purpose=purpose,
                            semantic_text=view.semantic_text, text="query: " + view.semantic_text,
                            content_key=content_key(direction, purpose), usable=view.usable,
                            information=view.information, stages=view.stages, channels=view.channels))
    components = Components()
    alias_texts = set()
    for purpose, view in views.items():
        key = "text:" + view.semantic_text
        components.find(key)
        for alias in aliases[purpose]:
            alias_texts.add(alias)
            components.join(key, "alias:" + alias)
    index = TemplateIndex(alias_texts)
    for text in sorted(alias_texts):
        for other in sorted(index.matches(text)):
            components.join("alias:" + text, "alias:" + other)
    texts = sorted({r["text"] for r in raw})
    tokens = {}
    for name, (tokenize, provenance) in sorted(tokenizers.items()):
        ids = tokenize(texts)
        if len(ids) != len(texts):
            raise ValueError("tokenizer output cardinality mismatch")
        tokens[name] = dict(zip(texts, map(tuple, ids)))
        first = {}
        for text, ids in tokens[name].items():
            first.setdefault(ids, text)
            components.join("text:" + text.removeprefix("query: "),
                            "text:" + first[ids].removeprefix("query: "))
    family_map = {text: "leakage-" + digest(components.find("text:" + text))[:24]
                  for text in {r["semantic_text"] for r in raw}}
    eligibility = defaultdict(set)
    for r in raw:
        eligibility[family_map[r["semantic_text"]]].add(company_owner[r["company"]])
    owners = {f: owner_for(f, ps, seed) for f, ps in sorted(eligibility.items())}
    parts = {p: [] for p in PARTS}
    purged = Counter()
    for r in raw:
        p = company_owner[r["company"]]
        family = family_map[r["semantic_text"]]
        if owners[family] == p:
            parts[p].append(dict(r, template_family=family))
        else:
            purged[p] += 1
    sets = {}
    for p, rows in parts.items():
        sets[p] = dict(companies={r["company"] for r in rows},
                       families={r["template_family"] for r in rows},
                       texts={r["text"] for r in rows},
                       aliases={a for r in rows for a in aliases[r["purpose"]]})
        for name in tokens:
            sets[p]["tokens:" + name] = {tokens[name][r["text"]] for r in rows}
    intersections = {f"{a}__{b}": {k: len(sets[a][k] & sets[b][k]) for k in sets[a]} for a, b in PAIRS}
    for a, b in PAIRS:
        heldout_index = TemplateIndex(sets[b]["aliases"])
        intersections[f"{a}__{b}"]["near_template_pairs"] = sum(len(heldout_index.matches(t)) for t in sets[a]["aliases"])
    if any(n for counts in intersections.values() for n in counts.values()):
        raise ValueError(f"leakage: {intersections}")
    # Do not leave a path looking like a valid frozen dataset after failure.
    staging = out.with_name(out.name + ".building")
    staging.mkdir(parents=True, exist_ok=False)
    from zavozik_ml.classify import text as legacy_text, augment
    from zavozik_ml.classify_v2 import splitting, text as previous_text
    report = dict(protocol=PROTOCOL, text_version=TEXT_VERSION, source_kind=source_kind,
                  source_sha256=sha256_file(source), company_manifest_sha256=sha256_file(company_manifest),
                  seed=seed, targets="none", independent_external_test=False,
                  evaluation_scope="development_only; same historical source, old final consumed",
                  policy="Fixed companies; connected alias/near-template/actual-token closure; label-free weighted hash ownership; purge non-owner rows",
                  density_unit="exact direction+semantic_text; leakage family is NOT a semantic category",
                  intersections=intersections, source_rows=len(raw),
                  source_unique_direction_texts=len({(r["direction"], r["text"]) for r in raw}),
                  source_usable_direction_texts=len({(r["direction"], r["text"]) for r in raw if r["usable"]}),
                  leakage_families=len(owners),
                  tokenizers={name: prov for name, (_, prov) in sorted(tokenizers.items())},
                  source_files_sha256={str(p.relative_to(Path(__file__).parents[2])): sha256_file(p) for p in
                      (Path(__file__), Path(__file__).with_name("normalization.py"), Path(legacy_text.__file__),
                       Path(augment.__file__), Path(splitting.__file__), Path(previous_text.__file__))})
    try:
        for p, rows in parts.items():
            write_rows(staging / f"{p}.jsonl", rows)
            groups = defaultdict(list)
            for r in rows:
                groups[(r["direction"], r["semantic_text"])].append(r)
            unique = []
            for _, values in sorted(groups.items()):
                r = min(values, key=lambda r: r["id"])
                unique.append(dict(r, count=len(values), companies=sorted({v["company"] for v in values})))
            write_rows(staging / f"{p}_unique.jsonl", unique)
            report[p] = dict(rows=len(rows), unique=len(unique), usable_unique=sum(r["usable"] for r in unique),
                             families=len(sets[p]["families"]), companies=len(sets[p]["companies"]),
                             purged_rows=purged[p], sha256=sha256_file(staging / f"{p}.jsonl"),
                             unique_sha256=sha256_file(staging / f"{p}_unique.jsonl"))
        (staging / "registry.json").write_text(json.dumps(dict(families=family_map, owners=owners), ensure_ascii=False, sort_keys=True) + "\n")
        report["registry_sha256"] = sha256_file(staging / "registry.json")
        (staging / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        staging.rename(out)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--company-manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--base", type=Path, action="append", required=True)
    p.add_argument("--candidate-bases", action="store_true", help="Use versioned E5/Qwen input recipes rather than legacy E5-only tokens")
    p.add_argument("--source-kind", choices=("case_synthetic", "anonymized_bank"), required=True)
    a = p.parse_args()
    from transformers import AutoTokenizer
    tokenizers = {}
    for base in a.base:
        path = base / "base_source.json"
        if a.candidate_bases and not path.exists():
            path = base / "tokenizer_source.json"
        prov = json.loads(path.read_text())
        if a.candidate_bases:
            from .candidate_models import MODELS, tokenizer_for
            matches = [n for n, spec in MODELS.items() if spec.model_id == prov["model_id"] and spec.revision == prov["revision"]]
            if len(matches) != 1:
                raise ValueError("unsupported candidate identity")
            name = prov["model_id"] + "@" + prov["revision"]
            if name in tokenizers:
                raise ValueError("duplicate tokenizer")
            tokenizers[name] = tokenizer_for(matches[0], base)
            continue
        for name, expected in prov["files_sha256"].items():
            if sha256_file(base / name) != expected:
                raise ValueError(f"base payload changed: {name}")
        name = prov["model_id"] + "@" + prov["revision"]
        if name in tokenizers:
            raise ValueError("duplicate tokenizer")
        tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True, trust_remote_code=False)
        def tokenize(texts, tokenizer=tokenizer):
            return tokenizer(texts, truncation=True, max_length=128)["input_ids"]
        tokenizers[name] = (tokenize, dict(prov, max_length=128, input_prefix="query: "))
    print(json.dumps(prepare(a.source, a.company_manifest, a.out, tokenizers, source_kind=a.source_kind), indent=2))


if __name__ == "__main__":
    main()

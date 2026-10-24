"""Two-level blind economic pair review, with bound endpoints and provenance.

No category IDs. Pairs are generated WITHIN a pre-purged partition, never split
after sampling. Same coarse / different fine is explicitly valid. Consensus
does not turn synthetic source text into an independent real-world benchmark.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import itertools
import json
from pathlib import Path
import random

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows, write_rows
from .preparation import PROTOCOL, PARTS, Components, digest

SCHEMA = "economic_pair_review_v2"
JUDGMENTS = ("same", "different", "uncertain")
INSTRUCTIONS = """Сравнивайте экономический смысл денежных потоков, а не общие слова.
coarse: одна ли крупная экономическая природа? fine: одна ли подробная группа?
same / different / uncertain. Число и названия категорий не задаются.
Разный предмет/роль важнее сходных документов, этапа оплаты и канала.
Coarse same + fine different допустимо; fine same + coarse different запрещено.
Если предмет/роль отсутствует, не додумывайте их; используйте uncertain.
Автомобиль без контекста не доказывает основное средство или перепродажу.
Указывайте обоснование по тексту. Работа модели/агента не является human gold.
"""


def endpoint(r):
    return {k: r[k] for k in ("content_key", "id", "direction", "purpose")}


def sample(corpus: Path, out: Path, per_partition=1000, seed=42):
    if out.exists():
        raise ValueError("review exists; refuse overwrite")
    meta = json.loads((corpus / "manifest.json").read_text())
    if meta["protocol"] != PROTOCOL or per_partition < 1:
        raise ValueError("purged discovery v2 corpus and positive sample size required")
    all_rows, owner = {}, {}
    for p in PARTS:
        path = corpus / f"{p}_unique.jsonl"
        if sha256_file(path) != meta[p]["unique_sha256"]:
            raise ValueError("corpus changed")
        rows = [r for r in read_rows(path) if r["usable"]]
        for r in rows:
            for key in ("content_key", "template_family"):
                value = (key, r[key])
                if value in owner and owner[value] != p:
                    raise ValueError("pair endpoints/families cross partitions")
                owner[value] = p
        all_rows[p] = rows
    out.mkdir(parents=True)
    report = dict(schema=SCHEMA, corpus_manifest_sha256=sha256_file(corpus / "manifest.json"),
                  source_kind=meta["source_kind"], independent_external_test=False,
                  scope="development pair review; historical synthetic source is not independent bank gold",
                  seed=seed, judgments_prefilled=False, instructions=INSTRUCTIONS, partitions={})
    for p, rows in all_rows.items():
        strata = defaultdict(list)
        for a, b in itertools.combinations(rows, 2):
            if a["direction"] != b["direction"]:
                continue  # direction is an observed constraint, not an easy negative target
            # Distinct exact texts, representative companies and leakage
            # families: cosmetic variants cannot inflate verified support.
            if a["template_family"] == b["template_family"] or a["company"] == b["company"]:
                continue
            wa, wb = set(a["semantic_text"].split()), set(b["semantic_text"].split())
            similarity = len(wa & wb) / max(1, len(wa | wb))
            stratum = "lexically_close" if similarity >= .3 else "other"
            strata[stratum].append((a, b))
        rng = random.Random(f"{seed}:{p}")
        chosen = []
        for kind, candidates in sorted(strata.items()):
            chosen.extend((kind, pair) for pair in rng.sample(candidates, min((per_partition + 1)//2, len(candidates))))
        selected = {(a["content_key"], b["content_key"]) for _, (a, b) in chosen}
        remaining = [(kind, pair) for kind, candidates in sorted(strata.items()) for pair in candidates
                     if (pair[0]["content_key"], pair[1]["content_key"]) not in selected]
        chosen.extend(rng.sample(remaining, min(max(0, per_partition-len(chosen)), len(remaining))))
        chosen = chosen[:per_partition]
        rng.shuffle(chosen)
        blind, private = [], []
        for kind, (a, b) in chosen:
            if rng.random() < .5:
                a, b = b, a
            identity = digest("\0".join(sorted((a["content_key"], b["content_key"]))))[:24]
            blind.append(dict(schema=SCHEMA, pair_id=identity, partition=p, left=endpoint(a), right=endpoint(b),
                              coarse=None, fine=None, rationale="", reviewer="", reviewer_kind=""))
            private.append(dict(pair_id=identity, sampling_stratum=kind,
                                families=[a["template_family"], b["template_family"]],
                                companies=[a["companies"], b["companies"]]))
        write_rows(out / f"{p}_blind.jsonl", blind)
        write_rows(out / f"{p}_private.jsonl", private)
        report["partitions"][p] = dict(pairs=len(blind), eligible=sum(map(len, strata.values())),
            sampling=dict(Counter(kind for kind, _ in chosen)),
            blind_sha256=sha256_file(out / f"{p}_blind.jsonl"), private_sha256=sha256_file(out / f"{p}_private.jsonl"))
    (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (out / "INSTRUCTIONS.txt").write_text(INSTRUCTIONS)
    return report


def validate_answer(row, original):
    for k in ("schema", "pair_id", "partition", "left", "right"):
        if row.get(k) != original[k]:
            raise ValueError("reviewed pair identity/input changed")
    if row.get("coarse") is None and row.get("fine") is None:
        return False
    if any(row.get(k) not in JUDGMENTS for k in ("coarse", "fine")):
        raise ValueError("both economic levels require a judgment")
    if (not row.get("reviewer", "").strip() or not row.get("rationale", "").strip() or
            row.get("reviewer_kind") not in ("human", "agent", "local_model")):
        raise ValueError("explicit reviewer identity/kind and rationale required")
    if row["fine"] == "same" and row["coarse"] != "same":
        raise ValueError("fine same requires coarse same")
    if row["coarse"] == "different" and row["fine"] != "different":
        raise ValueError("coarse different requires fine different")
    return True


def contradictions(rows):
    problems = []
    # Fine must-links imply coarse must-links; never silently repair a cycle.
    for level in ("coarse", "fine"):
        components = Components()
        for r in rows:
            if r[level] == "same":
                components.join(r["left"]["content_key"], r["right"]["content_key"])
        for r in rows:
            if r[level] == "different" and components.find(r["left"]["content_key"]) == components.find(r["right"]["content_key"]):
                problems.append(dict(pair_id=r["pair_id"], level=level, problem="cannot-link inside must-link component"))
    return problems


def consensus(review: Path, partition: str, answers: list[Path], out: Path, minimum_humans=2):
    if out.exists() or partition not in PARTS or minimum_humans < 1:
        raise ValueError("invalid consensus target/partition/reviewer count")
    meta = json.loads((review / "manifest.json").read_text())
    original_path = review / f"{partition}_blind.jsonl"
    if sha256_file(original_path) != meta["partitions"][partition]["blind_sha256"]:
        raise ValueError("review source changed")
    originals = {r["pair_id"]: r for r in read_rows(original_path)}
    votes = defaultdict(dict)
    weak = 0
    for path in answers:
        seen = set()
        for r in read_rows(path):
            identity = r["pair_id"]
            if identity in seen or identity not in originals:
                raise ValueError("unknown/duplicate pair id")
            seen.add(identity)
            if not validate_answer(r, originals[identity]):
                continue
            if r["reviewer_kind"] != "human":
                weak += 1
                continue
            reviewer = r["reviewer"].strip()
            if reviewer in votes[identity]:
                raise ValueError("repeated reviewer vote; copies are not independent annotation")
            votes[identity][reviewer] = r
    accepted, disagreements = [], []
    for identity, reviewers in sorted(votes.items()):
        if len(reviewers) < minimum_humans:
            continue
        judgments = {(r["coarse"], r["fine"]) for r in reviewers.values()}
        if len(judgments) != 1:
            disagreements.append(identity)
            continue
        coarse, fine = next(iter(judgments))
        accepted.append(dict(originals[identity], coarse=coarse, fine=fine,
            annotations=[{k: r[k] for k in ("reviewer", "reviewer_kind", "rationale")} for r in reviewers.values()],
            provenance="human_consensus", source_kind=meta["source_kind"]))
    conflicts = contradictions(accepted)
    result = dict(schema=SCHEMA, partition=partition, accepted=len(accepted), disagreements=disagreements,
                  transitive_conflicts=conflicts, minimum_humans=minimum_humans, weak_votes_excluded=weak,
                  status="FAIL_CONTRADICTIONS" if conflicts else "REVIEW_REQUIRED" if disagreements else "PASS" if accepted else "NO_LABELS",
                  independent_external_test=False, source_kind=meta["source_kind"],
                  review_manifest_sha256=sha256_file(review / "manifest.json"),
                  answers_sha256={str(p): sha256_file(p) for p in answers})
    out.mkdir(parents=True)
    # Never export inconsistent training targets.
    write_rows(out / "pairs.jsonl", [] if conflicts else accepted)
    (out / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--corpus", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pairs", type=int, default=1000)
    s = sub.add_parser("consensus")
    s.add_argument("--review", type=Path, required=True)
    s.add_argument("--partition", choices=PARTS, required=True)
    s.add_argument("--answers", type=Path, nargs="+", required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--minimum-humans", type=int, default=2)
    a = p.parse_args()
    result = sample(a.corpus, a.out, a.pairs) if a.command == "sample" else consensus(a.review, a.partition, a.answers, a.out, a.minimum_humans)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

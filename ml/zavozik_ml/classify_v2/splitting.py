"""Label-stratified template ownership with independent company partitions.

Companies stay in their existing90/30/30 split. Every template family belongs
to one partition; occurrences from companies in the other partitions are
purged. Joining companies by their shared templates would otherwise put most
of this highly repetitive dataset into one connected component.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import re

from .text import normalize

PROTOCOL = "company_purged_template_families_v3"
PARTITIONS = ("train", "calibration", "test")
NEAR_RATIO = .90
MIN_GRAM_JACCARD = .65
_DOC = re.compile(r"\b(?:(?:по|согласно)\s+)?(?:счету|счет|сч|договору|договор|дог|упд|акту|акт|накладной|накладная|накл)\b(?:\s+(?:номер|дата|0|от|г))*")
_RAIL = re.compile(r"\b(?:цифров\w*\s+рубл\w*|(?:через|посредством)\s+(?:сбп|систему быстрых платежей|интернет банк|банк клиент)|по qr коду)\b")
_SLOTS = re.compile(r"\b(?:номер|дата|мес|0|г|руб|рублей|рубля|коп)\b")


@lru_cache(maxsize=1)
def lexical_slots():
    # Existing augmentation dictionaries define fillable lexical slots too:
    # "оплата за {goods}" must not become different families for materials
    # versus equipment. This changes grouping only, never the model input.
    from zavozik_ml.classify.augment import BANKS, GOODS, GOODS_GEN, REGIONS, SERVICES
    result = []
    for marker, values in (("услуга", SERVICES), ("товар", GOODS + GOODS_GEN),
                           ("банк", BANKS), ("регион", REGIONS)):
        choices = sorted({normalize(v) for v in values}, key=lambda v: (-len(v), v))
        result.append((re.compile(r"\b(?:" + "|".join(re.escape(v) for v in choices) + r")\b"), f"<{marker}>"))
    return result


def structural_text(purpose: str) -> str:
    text = normalize(purpose)
    text = _RAIL.sub(" ", text)
    text = _DOC.sub(" ", text)
    text = _SLOTS.sub(" ", text)
    text = " ".join(text.split())
    text = re.sub(r"(?:\s+\b(?:по|за|от|на|с|года|период)\b)+$", "", text).strip()
    return text if re.search(r"[а-яa-z]", text) else "<uninformative>"


def template_text(purpose: str) -> str:
    text = structural_text(purpose)
    for pattern, marker in lexical_slots():
        text = pattern.sub(marker, text)
    return " ".join(text.split())


def signatures(purpose: str) -> set[str]:
    # Keep the unmasked alias too: a typo in a goods/service slot must not
    # evade family matching just because dictionary substitution missed it.
    return {structural_text(purpose), template_text(purpose)}


def grams(text: str) -> frozenset[str]:
    return frozenset(text[i:i+3] for i in range(max(1, len(text)-2)))


def near_template(a: str, b: str, ga=None, gb=None) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 8 or min(len(a), len(b)) / max(len(a), len(b)) < .8:
        return False
    ga, gb = grams(a) if ga is None else ga, grams(b) if gb is None else gb
    common = len(ga & gb)
    if common / len(ga | gb) < MIN_GRAM_JACCARD:
        return False
    a, b = sorted((a, b))  # SequenceMatcher tie-breaking must be deterministic
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= NEAR_RATIO


class TemplateIndex:
    def __init__(self, texts):
        self.texts = sorted(set(texts))
        self.grams = {t: grams(t) for t in self.texts}
        self.postings = defaultdict(set)
        for t, values in self.grams.items():
            for g in values:
                self.postings[g].add(t)

    def matches(self, text):
        values = grams(text)
        hits = Counter(t for g in values for t in self.postings.get(g, ()))
        return {t for t, common in hits.items()
                if common / (len(values) + len(self.grams[t]) - common) >= MIN_GRAM_JACCARD
                and near_template(text, t, values, self.grams[t])}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class TemplateRegistry:
    def __init__(self, families: dict[str, str], owners: dict[str, str]):
        self.families, self.owners = dict(families), dict(owners)
        self.index = TemplateIndex(families)
        self.heldout_index = TemplateIndex(t for t, f in families.items() if owners[f] != "train")

    def training_safe(self, row):
        family = row.get("template_family")
        if family in self.owners and self.owners[family] != "train":
            return False
        return not any(self.heldout_index.matches(text) for text in signatures(row.get("purpose", "")))

    def document(self):
        return {"protocol": PROTOCOL, "families": self.families, "owners": self.owners,
                "near_ratio": NEAR_RATIO, "min_gram_jaccard": MIN_GRAM_JACCARD}


def isolate(parts: dict[str, list[dict]], seed: int = 42):
    texts = {text for rows in parts.values() for r in rows for text in signatures(r.get("purpose", ""))}
    index = TemplateIndex(texts)
    parent = {t: t for t in texts}

    def find(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    for rows in parts.values():
        for row in rows:
            a, b = structural_text(row.get("purpose", "")), template_text(row.get("purpose", ""))
            a, b = sorted((find(a), find(b)))
            parent[b] = a
    for text in sorted(texts):
        for other in index.matches(text):
            a, b = sorted((find(text), find(other)))
            parent[b] = a
    families = {t: "family-" + digest(find(t))[:20] for t in sorted(texts)}
    counts, labels = defaultdict(Counter), defaultdict(Counter)
    for name, rows in parts.items():
        for row in rows:
            family = families[template_text(row.get("purpose", ""))]
            counts[family][name] += 1
            labels[family][row["label"]] += 1
    strata = defaultdict(list)
    for family in counts:
        # Weak labels are used only for ordinary split stratification. Final
        # statistical teacher targets are recomputed after purging.
        label = min(labels[family], key=lambda k: (-labels[family][k], k))
        strata[label].append(family)
    owners = {}
    for label in sorted(strata):
        groups = strata[label]
        n = len(groups)
        nc = max(1, int(n * .2)) if n >= 3 else 0
        nt = max(1, int(n * .2)) if n >= 2 else 0
        target = dict(zip(PARTITIONS, (n - nc - nt, nc, nt)))
        used = Counter()
        groups.sort(key=lambda f: (len(counts[f]), digest(f"{seed}:{f}")))
        for family in groups:
            eligible = list(counts[family])
            owner = max(eligible, key=lambda p: ((target[p] - used[p]) / max(target[p], 1),
                                                 counts[family][p], -PARTITIONS.index(p)))
            owners[family] = owner
            used[owner] += 1
    registry = TemplateRegistry(families, owners)
    kept, audit = {}, {}
    for name, rows in parts.items():
        retained = []
        for row in rows:
            family = families[template_text(row.get("purpose", ""))]
            if owners[family] == name:
                retained.append(dict(row, template_family=family, parent_id=row["id"],
                                     parent_company=row["company"]))
        kept[name] = retained
        audit[name] = {"source_rows": len(rows), "retained_rows": len(retained),
                       "purged_rows": len(rows) - len(retained),
                       "retained_families": len({r["template_family"] for r in retained})}
    return kept, registry, {"protocol": PROTOCOL, "partitions": audit,
                             "family_count": len(owners), "canonical_text_count": len(texts),
                             "policy": "Fixed company split plus deterministic weak-label-stratified family ownership; purge non-owner occurrences"}


def audit(records: dict[str, list[dict]], registry: TemplateRegistry) -> dict:
    from .data import operation
    from .text import dedupe_key, encoder_text
    sets = {}
    for name in PARTITIONS:
        rows = records[name]
        sets[name] = {"families": {r["template_family"] for r in rows},
                      "templates": {t for r in rows for t in signatures(r.get("purpose", ""))},
                      "normalized_inputs": {encoder_text(operation(r)) for r in rows},
                      "dedupe_keys": {dedupe_key(operation(r)) for r in rows},
                      "companies": {r.get("parent_company") or r.get("company") for r in rows} - {None, ""}}
    result = {}
    for i, a in enumerate(PARTITIONS):
        for b in PARTITIONS[i+1:]:
            entry = {key: len(sets[a][key] & sets[b][key]) for key in sets[a]}
            index = TemplateIndex(sets[b]["templates"])
            entry["near_template_pairs"] = sum(len(index.matches(t)) for t in sets[a]["templates"])
            result[f"{a}__{b}"] = entry
    if any(v for entry in result.values() for v in entry.values()):
        raise ValueError(f"cross-partition leakage detected: {result}")
    if any(r.get("source") != "case_weak" for name in ("calibration", "test") for r in records[name]):
        raise ValueError("primary calibration/test must not contain augmented or synthetic observations")
    if any(not registry.training_safe(r) for r in records["train"]):
        raise ValueError("training augmentation crossed a held-out template family")
    return {"passed": True, "protocol": PROTOCOL, "pairwise_intersections": result,
            "calibration_test_augmented_rows": 0}

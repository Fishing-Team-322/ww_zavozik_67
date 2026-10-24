"""Discover an entire category inventory from independent semantic vectors.

No category targets, initial category count, named seed prototypes or fallback
to legacy classes. Geometry scores are NOT correctness probabilities.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from zavozik_ml.classify_v2.model import unit, sha256_file
from .corpus import STOPS, informative


@dataclass(frozen=True)
class Settings:
    min_cluster_size: int = 3
    min_samples: int = 2
    min_companies: int = 2
    margin: float = .01
    radius_quantile: float = .95
    min_radius: float = .005
    max_radius: float = .20

    def validate(self):
        if self.min_cluster_size < 3 or not 2 <= self.min_samples <= self.min_cluster_size or self.min_companies < 1:
            raise ValueError("invalid independent support requirements")
        if not 0 <= self.margin <= 1 or not 0 < self.radius_quantile <= 1 or not 0 < self.min_radius <= self.max_radius <= 2:
            raise ValueError("invalid assignment parameters")


def vectors(x, n=None, dim=None):
    x = np.asarray(x, np.float32)
    if x.ndim != 2 or (n is not None and len(x) != n) or (dim is not None and x.shape[1] != dim):
        raise ValueError("embedding shape mismatch")
    if not 1 <= x.shape[1] <= 4096 or not np.isfinite(x).all() or (np.linalg.norm(x, axis=1) < 1e-8).any():
        raise ValueError("invalid embedding values")
    # Preserve already normalized float32 bytes on immutable save/load.
    # Renormalizing them again can change a final bit and the content version.
    return x if np.all(np.abs(np.linalg.norm(x, axis=1)-1) < 1e-5) else unit(x)


def family_points(rows, x):
    """One actual medoid per (direction, independent template family).

    Repeating an operation a million times has no effect. All distinct purpose
    views contribute equally to choosing the representative, never row counts.
    """
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        if r["direction"] not in ("in", "out"):
            raise ValueError("invalid direction")
        if informative(r["semantic_text"]):
            groups[(r["direction"], r["template_family"])].append(i)
    records, points = [], []
    for (direction, family), ids in sorted(groups.items()):
        # Deduplicate even if a caller did not supply *_unique.jsonl.
        unique = {}
        for i in sorted(ids, key=lambda j: (rows[j]["semantic_text"], rows[j]["id"])):
            unique.setdefault(rows[i]["semantic_text"], i)
        candidates = list(unique.values())
        center = unit(x[candidates].mean(0))
        medoid = candidates[int(np.argmax(x[candidates] @ center))]
        companies = sorted({c for i in ids for c in rows[i].get("companies", [rows[i]["company"]])})
        records.append(dict(direction=direction, template_family=family, companies=companies,
                            semantic_text=rows[medoid]["semantic_text"], id=rows[medoid]["id"]))
        points.append(x[medoid])
    return records, np.stack(points) if points else np.empty((0, x.shape[1]), np.float32)


def cluster_labels(records, points, settings: Settings):
    from sklearn.cluster import HDBSCAN
    labels = np.full(len(records), -1, np.int32)
    offset = 0
    for direction in ("in", "out"):
        positions = [i for i, r in enumerate(records) if r["direction"] == direction]
        if len(positions) < settings.min_cluster_size:
            continue
        result = HDBSCAN(min_cluster_size=settings.min_cluster_size, min_samples=settings.min_samples,
                         metric="euclidean", cluster_selection_method="eom", n_jobs=1,
                         allow_single_cluster=False, copy=True).fit_predict(points[positions])
        for label in sorted(set(result) - {-1}):
            members = [positions[i] for i in np.flatnonzero(result == label)]
            companies = {c for i in members for c in records[i]["companies"]}
            if len(companies) >= settings.min_companies:
                labels[members] = offset
                offset += 1
    return labels


def terms(text):
    words = [w for w in re.findall(r"[а-яa-z]{3,}", text) if w not in STOPS]
    return words + [a + " " + b for a, b in zip(words, words[1:])]


def titles(groups):
    counters = [Counter(t for text in group for t in set(terms(text))) for group in groups]
    doc_freq = Counter(t for c in counters for t in c)
    result = []
    for c in counters:
        ranked = sorted(c, key=lambda t: (-c[t] * (1 + np.log((1+len(counters))/(1+doc_freq[t]))) *
                                          (1.2 if " " in t else 1), t))
        chosen, used = [], set()
        for term in ranked:
            if not used.intersection(term.split()):
                chosen.append(term)
                used.update(term.split())
            if len(chosen) == 3:
                break
        result.append(" · ".join(chosen) or "Группа без характерных слов")
    return result


class CategoryInventory:
    def __init__(self, document: dict, centers: np.ndarray):
        self.document = json.loads(json.dumps(document))
        self.settings = Settings(**document["settings"])
        self.settings.validate()
        self.categories = self.document["categories"]
        self.encoder_version = self.document["encoder_version"]
        self.centers = vectors(centers, len(self.categories), document["embedding_dim"])
        ids = [c["id"] for c in self.categories]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate category IDs")
        for c in self.categories:
            if c["direction"] not in ("in", "out") or not self.settings.min_radius <= c["radius"] <= self.settings.max_radius:
                raise ValueError("invalid category geometry")
        # Both semantic content and geometry bind the taxonomy version.
        self.document.pop("taxonomy_version", None)
        digest = hashlib.sha256(json.dumps(self.document, sort_keys=True, ensure_ascii=False).encode() + self.centers.tobytes()).hexdigest()[:20]
        self.version = "discovered-v1-" + digest
        self.document["taxonomy_version"] = self.version

    def assign(self, rows, x, encoder_version):
        if encoder_version != self.encoder_version:
            raise ValueError("incompatible embedding model/version")
        x = vectors(x, len(rows), self.document["embedding_dim"])
        results = []
        for row, value in zip(rows, x):
            if row["direction"] not in ("in", "out"):
                raise ValueError("invalid direction")
            eligible = [i for i, c in enumerate(self.categories) if c["direction"] == row["direction"]]
            scores = self.centers[eligible] @ value
            order = sorted(range(len(eligible)), key=lambda j: (-float(scores[j]), self.categories[eligible[j]]["id"]))
            nearest = [dict(category_id=self.categories[eligible[j]]["id"], title=self.categories[eligible[j]]["title"],
                            similarity=float(np.clip(scores[j], -1, 1))) for j in order[:3]]
            margin = float(scores[order[0]] - scores[order[1]]) if len(order) > 1 else None
            category, reason = None, "no_category"
            if not informative(row["semantic_text"]):
                reason = "insufficient_text"
            elif order:
                candidate = self.categories[eligible[order[0]]]
                distance = max(0., 1-float(scores[order[0]]))
                if distance > candidate["radius"]:
                    reason = "outside_cluster"
                elif margin is not None and margin < self.settings.margin:
                    reason = "ambiguous"
                else:
                    category, reason = candidate, "assigned"
            results.append(dict(id=row.get("id", ""), category_id=category["id"] if category else None,
                                category_title=category["title"] if category else None, status=reason,
                                candidates=nearest, similarity=nearest[0]["similarity"] if nearest else None,
                                margin=margin, taxonomy_version=self.version, encoder_version=self.encoder_version,
                                score_kind="cosine_geometry_not_probability"))
        return results

    def save(self, out: Path):
        if out.exists():
            raise ValueError("inventory exists; immutable output required")
        out.mkdir(parents=True)
        np.save(out / "centers.npy", self.centers, allow_pickle=False)
        (out / "taxonomy.json").write_text(json.dumps(self.document, ensure_ascii=False, indent=2) + "\n")
        manifest = {name: sha256_file(out / name) for name in ("centers.npy", "taxonomy.json")}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    @classmethod
    def load(cls, directory: Path):
        manifest = json.loads((directory / "manifest.json").read_text())
        if set(manifest) != {"centers.npy", "taxonomy.json"}:
            raise ValueError("incomplete inventory manifest")
        for name, digest in manifest.items():
            if sha256_file(directory / name) != digest:
                raise ValueError("inventory checksum mismatch")
        document = json.loads((directory / "taxonomy.json").read_text())
        result = cls(document, np.load(directory / "centers.npy", allow_pickle=False))
        if result.version != document["taxonomy_version"]:
            raise ValueError("taxonomy version mismatch")
        return result


def fit_inventory(rows, embeddings, encoder_version, settings=Settings(), parent: CategoryInventory | None = None):
    settings.validate()
    x = vectors(embeddings, len(rows))
    if parent is not None:
        if parent.encoder_version != encoder_version or asdict(settings) != parent.document["settings"]:
            raise ValueError("incompatible parent inventory")
        assignments = parent.assign(rows, x, encoder_version)
        # Border ambiguity is evidence of an existing category boundary, not a
        # new phenomenon. Only genuine outside/no-category residuals can grow.
        keep = [i for i, a in enumerate(assignments) if a["status"] in ("outside_cluster", "no_category")]
        rows, x = [rows[i] for i in keep], x[keep]
    records, points = family_points(rows, x)
    labels = cluster_labels(records, points, settings)
    categories, centers = [], []
    groups = [[records[i]["semantic_text"] for i in np.flatnonzero(labels == label)] for label in sorted(set(labels)-{-1})]
    names = titles(groups)
    for label, title in zip(sorted(set(labels)-{-1}), names):
        positions = np.flatnonzero(labels == label)
        values = points[positions]
        center = unit(values.mean(0))
        # Leave the family's own vector out when measuring its distance.
        loo = unit(values.sum(0)[None] - values)
        distances = np.clip(1 - np.sum(values * loo, axis=1), 0, 2)
        radius = max(settings.min_radius, min(settings.max_radius, float(np.quantile(distances, settings.radius_quantile))))
        direction = records[int(positions[0])]["direction"]
        if parent is not None:
            previous = [i for i, c in enumerate(parent.categories) if c["direction"] == direction]
            if any(1-float(parent.centers[i] @ center) <= max(radius, parent.categories[i]["radius"]) + settings.margin for i in previous):
                continue  # Avoid auto-creating synonyms of an existing group.
        families = sorted(records[int(i)]["template_family"] for i in positions)
        identity = hashlib.sha256((encoder_version + direction + "|".join(families)).encode()).hexdigest()[:16]
        order = positions[np.argsort(-(values @ center), kind="stable")]
        categories.append(dict(id="auto_" + identity, title=title, direction=direction,
                               title_status="auto_extractive", attributes_status="unknown_requires_separate_evidence",
                               independent_families=len(families), companies=len({c for i in positions for c in records[int(i)]["companies"]}),
                               support_families=families, radius=radius,
                               representative_ids=[records[int(i)]["id"] for i in order[:5]]))
        centers.append(center)
    added = len(categories)
    if parent is not None:
        categories = parent.categories + categories
        centers = list(parent.centers) + centers
    dimension = x.shape[1]
    document = dict(format_version=1, encoder_version=encoder_version, embedding_dim=dimension,
                    settings=asdict(settings), categories=categories,
                    parent_taxonomy_version=parent.version if parent else None,
                    category_source="fully_automatic_unsupervised_train_only",
                    probability_calibration="none", seed_categories=[], fixed_category_count=None)
    inventory = parent if parent is not None and added == 0 else CategoryInventory(
        document, np.stack(centers) if centers else np.empty((0, dimension), np.float32))
    report = dict(independent_points=len(points), noise_points=int((labels < 0).sum()),
                  discovered_categories=len(categories)-(len(parent.categories) if parent else 0),
                  total_categories=len(categories), categories_hand_labeled=False)
    return inventory, report, (records, points, labels)

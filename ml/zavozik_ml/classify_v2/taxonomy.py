"""The artifact's versioned taxonomy is the only source of output vocabularies."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

DEFAULT_TAXONOMY = Path(__file__).with_name("taxonomy.json")


class Taxonomy:
    def __init__(self, document: dict):
        self.document = copy.deepcopy(document)
        version = self.document.get("taxonomy_version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("taxonomy_version must be nonempty")
        for group in ("categories", "channels", "tags"):
            items = self.document.get(group)
            if not isinstance(items, list) or not items:
                raise ValueError(f"taxonomy {group} must be nonempty")
            keys = []
            for item in items:
                if not isinstance(item, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item.get("key", "")):
                    raise ValueError(f"invalid {group} key")
                if not isinstance(item.get("title_ru"), str) or not item["title_ru"].strip():
                    raise ValueError(f"missing {group} title")
                keys.append(item["key"])
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {group} key")
        for item in self.document["categories"]:
            if not isinstance(item.get("description_ru"), str) or not item["description_ru"].strip():
                raise ValueError("category description required")
            a = item.get("attributes", {})
            if (set(a) != {"flow", "direction", "mandatory", "regular_hint"}
                    or a["flow"] not in ("business", "owner") or a["direction"] not in ("in", "out", "both")
                    or type(a["mandatory"]) is not bool or type(a["regular_hint"]) is not bool):
                raise ValueError("invalid category attributes")

    @classmethod
    def load(cls, path: Path = DEFAULT_TAXONOMY) -> "Taxonomy":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @property
    def version(self) -> str:
        return self.document["taxonomy_version"]

    def keys(self, group: str) -> tuple[str, ...]:
        return tuple(x["key"] for x in self.document[group])

    @property
    def categories(self) -> tuple[str, ...]:
        return self.keys("categories")

    @property
    def channels(self) -> tuple[str, ...]:
        return self.keys("channels")

    @property
    def tags(self) -> tuple[str, ...]:
        return self.keys("tags")

    def category(self, key: str) -> dict:
        for item in self.document["categories"]:
            if item["key"] == key:
                return copy.deepcopy(item)
        raise KeyError(key)

    def without(self, keys: set[str]) -> "Taxonomy":
        if not keys <= set(self.categories):
            raise ValueError("unknown categories to hide")
        d = copy.deepcopy(self.document)
        d["categories"] = [x for x in d["categories"] if x["key"] not in keys]
        d["taxonomy_version"] += "-hide-" + "-".join(sorted(keys))
        return Taxonomy(d)

    def adding(self, category: dict, version: str) -> "Taxonomy":
        if category.get("key") in self.categories or version == self.version:
            raise ValueError("new category and new taxonomy_version required")
        d = copy.deepcopy(self.document)
        d["categories"].append(copy.deepcopy(category))
        d["taxonomy_version"] = version
        return Taxonomy(d)

    def dumps(self) -> str:
        return json.dumps(self.document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.dumps().encode()).hexdigest()

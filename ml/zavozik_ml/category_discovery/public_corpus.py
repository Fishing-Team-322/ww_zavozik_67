"""Bounded multilingual public-purpose pilot, split BEFORE pair generation.

Does not reuse Russian-only word tokenization or budget codes as categories.
Near-template closure is heuristic; zero intersections refer to these explicit
rules and actual tokenizer inputs, not a proof of semantic independence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import shutil
import unicodedata

from zavozik_ml.classify_v2.model import sha256_file
from zavozik_ml.classify_v2.splitting import TemplateIndex
from .candidate_models import MODELS, tokenizer_for
from .corpus import read_rows, write_rows
from .normalization import PurposeView
from .preparation import Components, PARTS, PAIRS, digest, owner_for

PROTOCOL = "public_multilingual_company_template_token_v1"
TEXT_VERSION = "public_purpose_unicode_query_v1"
_DATE = r"\b\d{1,4}[./-]\d{1,2}[./-]\d{1,4}(?:\s*[гр]\.?\b)?"
_MONEY = r"\d+(?:\s+\d{3})*(?:[.,-]\d{1,2})?"
_CURRENCY = r"(?:грн\.?|руб(?:лей|ля|ль)?\.?|uah|₴|₽)"
_GENERIC = frozenset("оплата платеж платіж платiж плата розрахунок расчет часткова частичная остаточний остаточна остаточный остаточная остаток окончательный окончательная попередня попередній предварительная аванс авансовий авансовый доплата перерахування перечисление коштів кошти средства средств грошових грошові денежные денежных за по на від от і и в у з с із из згідно согласно договор договору договора договір угода угоди угодою акт акту акта накл накладна накладной рахунок рахунку рахунком счет счету счета послуга послуги услуг услуги номер дата період период без пдв ндс xxxx xx xxx гривень грн руб рублей сума сумма не указано невідомо призначення назначение data identifier account email".split())


def analyze(purpose):
    s = unicodedata.normalize("NFKC", str(purpose or "").replace("№", " __docnumber__ ")).lower().replace("ё", "е")
    s = s.replace("__docnumber__", "№")
    s = re.sub(r"\b(?:без\s+(?:пдв|ндс)|(?:пдв|ндс)\s+не\s+облагается)\b", " ", s)
    s = re.sub(r"(?:(?:в\s*т\.?\s*ч\.?|у\s*т\.?\s*ч\.?|в тому числі|в том числе)\s*)?\b(?:пдв|ндс)\s*(?:\(?\d+(?:[.,]\d+)?\s*%\)?\s*[-:=]?\s*(?:" + _MONEY + r")?|[:=]\s*" + _MONEY + r"|" + _MONEY + r"\s*" + _CURRENCY + r")(?:\s*" + _CURRENCY + r")?", " ", s)
    s = re.sub(r"\b(?:від|от)\s*(?=" + _DATE + ")", " ", s)
    s = re.sub(_DATE, " ", s)
    s = re.sub(r"(?:№|\bномер\b|#)\s*[\w/-]+(?:\.(?=\d)[\w/-]+)*", " ", s)
    s = re.sub(r"\b(?:кекв|кпквк|кпк|кфк|едрпоу|єдрпоу|инн|іпн|кпп|бик|мфо)\s*[:=]?\s*[\dxх/.-]+", " ", s)
    s = re.sub(r"\b(?:сумм?[аы]|сумою)\s*[:=]?\s*" + _MONEY + r"(?:\s*" + _CURRENCY + r")?", " ", s)
    s = re.sub(r"\b" + _MONEY + r"\s*" + _CURRENCY + r"(?!\w)", " ", s)
    s = re.sub(r"\b[xх]{2,}(?:[.,/-][\dxх]+)*\b", " ", s)
    s = re.sub(r"\b\d{4}\s*(?:року|рік|года|год|[гр]\.)", " ", s)
    # Codes preceding semicolon-delimited narrative are formatting, not class
    # targets. Numbers attached to an economic object survive in model input.
    s = re.sub(r"^\s*(?:[\d\s,./-]+;\s*)+", " ", s)
    tokens = re.findall(r"[^\W_]+", s, re.UNICODE)
    text = " ".join(tokens)
    useful = [w for w in tokens if any(c.isalpha() for c in w) and w not in _GENERIC]
    return PurposeView(text, "has_object_or_role" if useful else "generic_payment" if tokens else "empty", (), (), TEXT_VERSION)


def prepare(source: Path, bases: dict[str, Path], out: Path, limit=6000, seed=42):
    if out.exists() or limit < 100 or not bases:
        raise ValueError("immutable new output and pilot limit >=100 required")
    meta = json.loads((source / "source_manifest.json").read_text())
    path = source / "source_operations.jsonl"
    if meta["license"] != "CC-BY-4.0" or sha256_file(path) != meta["operations_sha256"]:
        raise ValueError("public source license/hash mismatch")
    raw = read_rows(path)
    groups = defaultdict(list)
    for r in raw:
        groups[r["company"]].append(r)
    # Cover many organizations before adding more rows from any one company.
    ordered = []
    for values in groups.values():
        for rank, r in enumerate(sorted(values, key=lambda r: digest(f"{seed}:{r['id']}"))):
            ordered.append((rank, digest(f"{seed}:{r['company']}:{r['id']}"), r))
    raw = [r for _, _, r in sorted(ordered)[:limit]]
    company_owner = {}
    for c in sorted({r["company"] for r in raw}):
        u = int(digest(f"{seed}:{c}"), 16) / 2**256
        company_owner[c] = "train" if u < .6 else "calibration" if u < .8 else "test"
    components, aliases, views = Components(), {}, {}
    for r in raw:
        view = analyze(r["purpose"])
        views[r["id"]] = view
        # Numeric object specifications are retained for encoder but collapsed
        # in a separate leakage-only alias. No semantic/category dictionaries.
        aliases[r["id"]] = {view.semantic_text, re.sub(r"\b\d+\b", "<number>", view.semantic_text)}
        for alias in aliases[r["id"]]:
            components.join("text:" + view.semantic_text, "alias:" + alias)
    alias_texts = {t for values in aliases.values() for t in values}
    print(f"public pilot {len(raw)} rows / {len({v.semantic_text for v in views.values()})} texts / {len(alias_texts)} aliases", flush=True)
    index = TemplateIndex(alias_texts)
    for i, text in enumerate(sorted(alias_texts)):
        for other in sorted(index.matches(text)):
            components.join("alias:" + text, "alias:" + other)
        if i and i % 1000 == 0:
            print(f"template closure {i}/{len(alias_texts)}", flush=True)
    texts = sorted({v.semantic_text for v in views.values()})
    token_maps, token_provenance = {}, {}
    for name, base in sorted(bases.items()):
        tokenize, provenance = tokenizer_for(name, base, text_version=TEXT_VERSION)
        encoded = tokenize(["query: " + t for t in texts])
        token_maps[name] = dict(zip(texts, map(tuple, encoded)))
        token_provenance[MODELS[name].model_id + "@" + MODELS[name].revision] = provenance
        first = {}
        for t, ids in token_maps[name].items():
            first.setdefault(ids, t)
            components.join("text:" + t, "text:" + first[ids])
    families = {t: "public-leakage-" + digest(components.find("text:" + t))[:24] for t in texts}
    eligible = defaultdict(set)
    for r in raw:
        eligible[families[views[r["id"]].semantic_text]].add(company_owner[r["company"]])
    owners = {f: owner_for(f, ps, seed) for f, ps in eligible.items()}
    parts, purged = {p: [] for p in PARTS}, Counter()
    for r in raw:
        view, part = views[r["id"]], company_owner[r["company"]]
        family = families[view.semantic_text]
        if owners[family] != part:
            purged[part] += 1
            continue
        parts[part].append(dict(id=r["id"], company=r["company"], direction=r["direction"], purpose=r["purpose"],
            semantic_text=view.semantic_text, text="query: " + view.semantic_text, template_family=family,
            content_key="public-content-"+digest(r["direction"] + "\0" + view.semantic_text)[:24],
            usable=view.usable, information=view.information, source=r["source"], source_date=r["source_date"]))
    sets = {}
    for part, rows in parts.items():
        sets[part] = dict(companies={r["company"] for r in rows}, families={r["template_family"] for r in rows},
                          texts={r["semantic_text"] for r in rows}, aliases={a for r in rows for a in aliases[r["id"]]})
        for name in token_maps:
            sets[part]["tokens:"+name] = {token_maps[name][r["semantic_text"]] for r in rows}
    intersections = {f"{a}__{b}": {k: len(sets[a][k] & sets[b][k]) for k in sets[a]} for a, b in PAIRS}
    for a, b in PAIRS:
        heldout = TemplateIndex(sets[b]["aliases"])
        intersections[f"{a}__{b}"]["near_template_pairs"] = sum(len(heldout.matches(t)) for t in sets[a]["aliases"])
    if any(v for entry in intersections.values() for v in entry.values()):
        raise ValueError(f"public cross-partition leakage: {intersections}")
    out.mkdir(parents=True)
    report = dict(protocol=PROTOCOL, text_version=TEXT_VERSION, source_kind="public_institution_transactions",
        source_manifest_sha256=sha256_file(source / "source_manifest.json"), source_rows=meta["retained_rows"],
        pilot_limit=limit, sampled_rows=len(raw), seed=seed, targets="none", independent_external_test=False,
        evaluation_scope="auxiliary multilingual public budget development; not Russian commercial gold",
        tokenizers=token_provenance, intersections=intersections,
        density_unit="exact direction+semantic_text, not leakage family or row count",
        source_files_sha256={"zavozik_ml/category_discovery/public_corpus.py": sha256_file(Path(__file__))})
    for part, rows in parts.items():
        write_rows(out / f"{part}.jsonl", rows)
        unique_groups = defaultdict(list)
        for r in rows:
            unique_groups[r["content_key"]].append(r)
        unique = [dict(min(rs, key=lambda r:r["id"]), count=len(rs), companies=sorted({r["company"] for r in rs})) for _, rs in sorted(unique_groups.items())]
        write_rows(out / f"{part}_unique.jsonl", unique)
        report[part] = dict(rows=len(rows), unique=len(unique), usable_unique=sum(r["usable"] for r in unique),
            companies=len(sets[part]["companies"]), families=len(sets[part]["families"]), purged_rows=purged[part],
            sha256=sha256_file(out / f"{part}.jsonl"), unique_sha256=sha256_file(out / f"{part}_unique.jsonl"))
    (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    shutil.copyfile(Path(__file__), out / "public_corpus_source.py.txt")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--base", type=Path, action="append", required=True)
    p.add_argument("--limit", type=int, default=6000)
    a = p.parse_args()
    bases = {}
    for base in a.base:
        meta = json.loads((base / "base_source.json").read_text())
        names = [n for n, spec in MODELS.items() if spec.model_id == meta["model_id"] and spec.revision == meta["revision"]]
        if len(names) != 1 or names[0] in bases:
            raise ValueError("unsupported/duplicate candidate tokenizer")
        bases[names[0]] = base
    print(json.dumps(prepare(a.source, bases, a.out, a.limit), indent=2))


if __name__ == "__main__":
    main()

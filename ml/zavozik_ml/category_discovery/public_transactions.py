"""Qualify a frozen Spending.gov.ua snapshot as AUXILIARY public purposes.

Not Russian commercial-bank gold. No names/accounts/amounts/KEKV targets are
copied as model features; public purpose text may still contain personal names.
Keep the corpus local and do not describe pseudonymous organizations as fully
anonymized natural persons. Ministry attribution and CC BY 4.0 are preserved.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import shutil
import unicodedata

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import write_rows
from .preparation import digest

ABOUT = "https://spending.gov.ua/new/en/about-portal"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"


def organization(value):
    s = str(value or "").strip()
    # Individuals' tax IDs have 10 digits; unidentifiable parties are excluded.
    return s if re.fullmatch(r"\d{8}", s) and int(s) else None


def redact(text):
    # Minimize copied identifiers without fabricating a full de-identification
    # guarantee. Don't remove semantic words or Ukrainian letters.
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", " [account] ", text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", " [email] ", text, flags=re.I)
    text = re.sub(r"\b\d{10,}\b", " [identifier] ", text)
    return " ".join(text.split())


def qualify(response: Path, out: Path, snapshot_date: str, *, attribution_document: Path):
    day = date.fromisoformat(snapshot_date)
    if out.exists():
        raise ValueError("external snapshot exists; refuse overwrite")
    if not attribution_document.is_file():
        raise ValueError("saved primary source/license statement required")
    license_evidence = json.loads(attribution_document.read_text())
    if (license_evidence.get("source_url") != ABOUT or license_evidence.get("license") != "CC-BY-4.0" or
            license_evidence.get("license_url") != LICENSE or not license_evidence.get("excerpt")):
        raise ValueError("primary portal license evidence mismatch")
    raw = json.loads(response.read_text())
    if not isinstance(raw, list) or not raw:
        raise ValueError("empty/non-list public snapshot")
    rows, seen, excluded = [], set(), Counter()
    for item in raw:
        for key in ("id", "payer_edrpou", "recipt_edrpou", "payment_details", "trans_date"):
            if key not in item:
                raise ValueError("public API schema changed")
        transaction_id = str(item["id"])
        if transaction_id in seen:
            raise ValueError("duplicate transaction id")
        seen.add(transaction_id)
        payer, recipient = organization(item["payer_edrpou"]), organization(item["recipt_edrpou"])
        if not payer or not recipient:
            excluded["non_organization_or_unknown_party"] += 1
            continue
        purpose = redact(item["payment_details"])
        if not purpose:
            excluded["empty_purpose"] += 1
            continue
        # Date filter must bind the actual downloaded records, not just the
        # URL. The API trans_date can include a timestamp after YYYY-MM-DD.
        if str(item["trans_date"])[:10] != day.isoformat():
            raise ValueError("transaction outside requested day")
        rows.append(dict(id="spending-" + digest(transaction_id)[:24],
            company="spending-org-" + digest(payer)[:24],
            counterparty_group="spending-org-" + digest(recipient)[:24],
            direction="out", purpose=purpose, source_date=day.isoformat(),
            source="spending_gov_ua_public_treasury", source_kind="public_institution_transactions",
            source_record_sha256=digest(json.dumps(item, ensure_ascii=False, sort_keys=True))))
    if not rows:
        raise ValueError("no qualified organization-to-organization purposes")
    out.mkdir(parents=True)
    write_rows(out / "source_operations.jsonl", rows)
    shutil.copyfile(attribution_document, out / ("portal_attribution" + attribution_document.suffix))
    # Data preparations also need recoverable source provenance, even before
    # a model fit exists. Historical .txt copies are never imported/executed.
    snapshot = out / "source_snapshot"
    snapshot.mkdir()
    paths = [Path(__file__), Path(__file__).with_name("corpus.py"), Path(__file__).with_name("preparation.py")]
    for path in paths:
        shutil.copyfile(path, snapshot / (path.name + ".txt"))
    report = dict(schema="public_payment_source_qualification_v1", source="Ministry of Finance of Ukraine / Spending.gov.ua",
        source_url=f"https://api.spending.gov.ua/api/v2/api/transactions/?startdate={day}&enddate={day}",
        about_url=ABOUT, license="CC-BY-4.0", license_url=LICENSE,
        license_evidence_sha256=sha256_file(attribution_document),
        raw_response_sha256=sha256_file(response), raw_bytes=response.stat().st_size,
        snapshot_date=day.isoformat(), qualified_at_utc=datetime.now(timezone.utc).isoformat(),
        raw_rows=len(raw), retained_rows=len(rows), excluded=dict(excluded),
        payer_organizations=len({r["company"] for r in rows}),
        exact_unique_purposes=len({r["purpose"] for r in rows}),
        purposes_with_ukrainian_specific_letters=sum(bool(re.search("[іїєґІЇЄҐ]", r["purpose"])) for r in rows),
        language_scope="Ukrainian/mixed public purposes; letter count is not language identification",
        gold_labels=0, inferred_categories=0, targets="none", training_approved_scope="auxiliary_research_only",
        feature_fields=["direction", "purpose"],
        lineage_only_fields=["id", "company", "counterparty_group", "source_date", "source_record_sha256"],
        changes="Organization IDs hashed; source names/accounts/amounts/budget labels omitted; basic identifier redaction in text; no translation or invented descriptions",
        limits=["Public-budget domain and different language/jurisdiction; not a substitute for Russian commercial bank statements",
                "One day; no claim of representative economic coverage or semantic correctness",
                "Purpose text may retain personal names; not certified de-identified",
                "Public text may have appeared in pretrained encoder data; overlap unknown",
                "Deduplication, template/company/token split, review and fit must happen later before any quality claim"],
        operations_sha256=sha256_file(out / "source_operations.jsonl"), code_sha256=sha256_file(Path(__file__)),
        preparation_source_sha256={p.name: sha256_file(p) for p in paths})
    (out / "source_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (out / "ATTRIBUTION.txt").write_text(
        f"Source: Ministry of Finance of Ukraine, Spending.gov.ua. {ABOUT}\n"
        f"Data snapshot: {day}. License: Creative Commons Attribution 4.0 International, {LICENSE}\n"
        "Changes: filtered organization-to-organization rows; pseudonymized identifiers; omitted account/name/amount/budget fields; basic text identifier redaction. No endorsement implied.\n"
        "Auxiliary research corpus, not Russian commercial-bank gold and not independently human-labeled.\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--response", type=Path, required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--attribution-document", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(qualify(a.response, a.out, a.date, attribution_document=a.attribution_document), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

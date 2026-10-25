"""Quarantine explicit obligation conflicts; never invent replacement labels.

These are source-evidence constraints, not discovered category IDs or a closed
category vocabulary. In particular, a payment BASE is not its actual obligation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from zavozik_ml.classify_v2.model import sha256_file
from .audit_relations import audit
from .corpus import read_rows,write_rows


def obligation_evidence(text):
    text=text.casefold().replace("ё","е").replace("і","и").replace("i","и")
    text=re.sub(r"\d+", " ", text)
    tags=set()
    if re.search(r"\b(?:ндфл|пдфо)\b|подат\w*\s+(?:з\s+)?доход\w*\s+ф[иі]з",text):tags.add("personal_income_tax")
    if re.search(r"\b(?:єсв|есв)\b|єдин\w*.{0,40}(?:соц|страх|внес)|страхов\w*\s+взнос",text):tags.add("social_contribution")
    if re.search(r"(?:в[ийи]йськов\w*|вийськов\w*|военн\w*)\s+(?:зб[иі]р\w*|сбор\w*)",text):tags.add("military_levy")
    if re.search(r"податк\w*\s+(?:и|та)\s+збор",text):tags.add("unspecified_statutory_remittance")
    employee=not tags and bool(re.search(r"в[иі]дпуск\w*|отпускн\w*|зарплат\w*|заработн\w*|зароб[иі]тн\w*|л[иі]карнян\w*|больничн\w*|мат\w*\s+забез\w*|матзабез\w*|тимчасов\w*\s+непрац\w*|ваг[иі]тн\w*",text))
    return tags,employee



def unspecified_object(text):
    """A generic object cannot establish a specific subgroup, even if cosine is high."""
    return bool(re.search(r"\bза\s+(?:товар(?:ы|а|ов)?|услуг[иу]?|(?:выполненн\w*\s+)?работ[ыау]?)(?:\s+(?:по|под)\b|\s*$)",text.casefold()))


def conflict(left,right,level):
    if level=="fine" and (unspecified_object(left) or unspecified_object(right)):return "specific_object_not_established"
    a,ea=obligation_evidence(left);b,eb=obligation_evidence(right)
    if a and eb or b and ea:return "statutory_remittance_vs_employee_payment"
    if level=="fine" and a and b and not a.intersection(b):return "distinct_explicit_statutory_obligations"
    return None


def clean(source: Path,out: Path):
    if out.exists():raise ValueError("corrected label output is immutable")
    rows=read_rows(source);kept=[];quarantined=[]
    for r in rows:
        reasons=[conflict(r['left'].get('semantic_text',r['left']['purpose']),r['right'].get('semantic_text',r['right']['purpose']),level)
                 for level in ('coarse','fine') if r[level]=='same']
        reasons=[reason for reason in reasons if reason]
        if reasons:quarantined.append(dict(pair_id=r['pair_id'],reasons=sorted(set(reasons))))
        else:kept.append(r)
    before=audit(rows)
    while kept:
        report=audit(kept);bad=set()
        for level in report['levels'].values():
            for c in level['conflicts']:bad.update([c['different_pair_id']]+c['same_path_pair_ids'])
        if not bad:break
        quarantined.extend(dict(pair_id=k,reasons=['contradictory_equivalence_cycle']) for k in sorted(bad))
        kept=[r for r in kept if r['pair_id'] not in bad]
    if not kept:raise ValueError('no usable labels remain after quarantine')
    after=audit(kept);out.mkdir(parents=True);write_rows(out/'pairs.jsonl',kept)
    report=dict(source_sha256=sha256_file(source),code_sha256=sha256_file(Path(__file__)),raw_pairs=len(rows),accepted=len(kept),
        quarantined=quarantined,before=before,after=after,label_provenance='local_model_weak_not_human_gold',
        labels_reversed_or_guessed=False,semantic_accuracy=None,final_test_read=False,
        corrected_pairs_sha256=sha256_file(out/'pairs.jsonl'))
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=clean(a.source,a.out);print(json.dumps(dict(raw=r['raw_pairs'],accepted=r['accepted'],quarantined=len(r['quarantined']))))


if __name__=='__main__':main()

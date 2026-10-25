"""Separate M6 compatibility projection; native discovered categories stay open.

No Torch/MLX/LightGBM imports. Preserve original operations, not embedding text.
This layer cannot manufacture economic certainty from an unassigned embedding.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import math
import re

from zavozik_ml.classify.text import CATEGORIES

INTERNAL={"own_transfer","owner_loan"}
INFLOW={"revenue_acquiring","revenue_sbp","revenue_cash","revenue_b2b","revenue_marketplace","refund"}
OUTFLOW={"supplier","salary","tax","rent","utilities","leasing","bank_fee","marketing","services","enforcement"}
LOAN=re.compile(r"\b(?:займ\w*|заем\w*|кредит\w*|ссуд\w*)",re.I)
OWNER=re.compile(r"учредител\w*|участник\w*|собственник\w*|владельц\w*",re.I)
OWN_ACCOUNTS=re.compile(r"между\s+(?:своими|собственн\w*)\s+(?:расчетн\w*\s+)?счет\w*",re.I)


def iso(value):
    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:
        raise ValueError("strict YYYY-MM-DD date required")
    return date.fromisoformat(value)


def money(value):
    try:
        amount=Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid operation amount") from exc
    if not amount.is_finite() or not 0<=amount<=Decimal('1e15'):
        raise ValueError("operation amount must be finite, nonnegative and bounded")
    return amount


@dataclass(frozen=True)
class ProjectedOperations:
    transactions: tuple[dict,...]
    semantic_assignments: tuple[dict,...]
    warnings: tuple[str,...]


def project_operations(operations,assignments,projection,*,taxonomy_version):
    """Projection is explicitly versioned metadata, never a title keyword map.

    Optional verified counterparty_relation comes from the caller's identity
    data, not the model: same_legal_entity / owner / bank / external / unknown.
    It is NOT a new ForecastRequest field and is never sent as a raw identifier.
    """
    if projection.get("taxonomy_version")!=taxonomy_version:
        raise ValueError("forecast projection/taxonomy versions differ")
    by_id={a["id"]:a for a in assignments}
    if len(by_id)!=len(assignments):raise ValueError("duplicate assignment id")
    seen,txs,semantics,warnings=set(),[],[],set()
    for op in operations:
        identity=op["id"]
        if not isinstance(identity,str) or not identity or identity in seen:
            raise ValueError("unique nonempty operation id required")
        seen.add(identity);iso(op["date"]);amount=money(op["amount"])
        direction=op["direction"]
        if direction not in ("in","out"):raise ValueError("invalid operation direction")
        raw=op.get("purpose","")
        if not isinstance(raw,str):raise ValueError("original purpose must be text")
        normalized=raw.lower().replace("ё","е")
        assignment=by_id.get(identity,{})
        native=(assignment.get("category_id") if assignment.get("status")=="assigned" else
                assignment.get("coarse_category_id") if assignment.get("status")=="coarse_only" else None)
        entry=projection.get("categories",{}).get(native,{}) if native else {}
        category=entry.get("forecast_category","other")
        if projection.get("fallback")=="source_text_evidence_v1":
            from .forecast_evidence import hint
            explicit=hint(raw,direction)
            if explicit!='other':category=explicit
            if category.startswith("revenue_"):entry=dict(entry,flow_role="sales_revenue")
        if category not in CATEGORIES:raise ValueError("projection contains unsupported forecast category")
        relation=op.get("counterparty_relation","unknown")
        if relation not in ("same_legal_entity","owner","bank","external","unknown"):
            raise ValueError("invalid counterparty relationship evidence")
        explicit_owner_loan=bool(LOAN.search(normalized) and OWNER.search(normalized))
        explicit_own=bool(OWN_ACCOUNTS.search(normalized))
        # Critical scope decisions are per operation, not inferred from a broad
        # group title or the generic owner_money auxiliary tag.
        if relation in ("bank","external") and (explicit_own or explicit_owner_loan):
            category="other";warnings.add("flow_scope_review_required")
        elif relation=="same_legal_entity" or explicit_own:
            category="own_transfer"
        elif explicit_owner_loan or relation=="owner" and LOAN.search(normalized):
            category="owner_loan"
        elif relation=="bank" and LOAN.search(normalized):
            category="loan_payment"
        elif category in INTERNAL:
            category="other";warnings.add("flow_scope_review_required")
        # A settlement rail does not prove sales revenue. Only a projected
        # revenue obligation can be further split into M6's rail-specific keys.
        if category.startswith("revenue_"):
            if entry.get("flow_role")!="sales_revenue":
                category="other";warnings.add("revenue_role_not_established")
            else:
                rail=assignment.get("channel")
                category={"card_acquiring":"revenue_acquiring","sbp":"revenue_sbp",
                          "cash":"revenue_cash","marketplace_payout":"revenue_marketplace"}.get(rail,category)
        if category in INFLOW and direction!="in" or category in OUTFLOW and direction!="out":
            category="other";warnings.add("m6_category_direction_unsupported")
        party=op.get("counterparty_id","")
        if not isinstance(party,str):raise ValueError("counterparty pseudonym must be text")
        if not party:warnings.add("counterparty_id_missing")
        txs.append(dict(id=identity,date=op["date"],amount=float(amount),direction=direction,
                        category=category,counterparty_id=party,purpose=raw))
        semantics.append(dict(id=identity,category_id=assignment.get("category_id"),
            coarse_category_id=assignment.get("coarse_category_id"),category_path=assignment.get("category_path",[]),
            status=assignment.get("status","unknown"),forecast_category=category,
            taxonomy_version=taxonomy_version,projection_version=projection.get("projection_version")))
    if set(by_id)-seen:raise ValueError("assignment id outside supplied operations")
    return ProjectedOperations(tuple(txs),tuple(semantics),tuple(sorted(warnings)))


def daily_history(projected,first_day,last_day,*,missing_dates=()):
    """Explicit statement coverage supplies missing_dates; no-op is not missing.

    All projected transactions are retained for M6, while own/owner movements
    are excluded from business inflow/outflow before residual reconciliation.
    """
    if "flow_scope_review_required" in projected.warnings:
        raise ValueError("cannot construct business history until internal flow scope is resolved")
    start,end=iso(first_day),iso(last_day)
    if start>end or (end-start).days>=3650:raise ValueError("invalid calendar history range")
    missing={iso(d) for d in missing_dates}
    if any(d<start or d>end for d in missing):raise ValueError("missing date outside history")
    days={start+timedelta(days=i):dict(inflow=Decimal(0),outflow=Decimal(0),by_category={})
          for i in range((end-start).days+1)}
    for tx in projected.transactions:
        d=iso(tx["date"])
        if d not in days:raise ValueError("transaction outside supplied daily history")
        if d in missing:raise ValueError("transaction on explicitly missing statement day")
        value=money(tx["amount"]);row=days[d];category=tx["category"]
        signed=value if tx["direction"]=="in" else -value
        row["by_category"][category]=row["by_category"].get(category,Decimal(0))+signed
        if category not in INTERNAL:
            row["inflow" if tx["direction"]=="in" else "outflow"]+=value
    return [dict(date=d.isoformat(),inflow=float(r["inflow"]),outflow=float(r["outflow"]),missing=d in missing,
                 by_category={k:float(v) for k,v in r["by_category"].items()}) for d,r in days.items()]


def forecast_request(message_type,projected,history,*,company_id,horizon_days=30,n_paths=600,seed=67,industry=""):
    """Fail on the stale Python schema instead of silently discarding field9."""
    field=message_type.DESCRIPTOR.fields_by_name.get("transactions")
    if field is None or field.number!=9:
        raise ValueError("ForecastRequest Python schema lacks transactions field9; regenerate from current proto")
    if "flow_scope_review_required" in projected.warnings:
        raise ValueError("unresolved internal flow scope")
    if not history:raise ValueError("daily history required")
    dates=[iso(r["date"]) for r in history]
    if any((b-a).days!=1 for a,b in zip(dates,dates[1:])):raise ValueError("calendar history has gaps")
    if any(tx["date"]<history[0]["date"] or tx["date"]>history[-1]["date"] for tx in projected.transactions):
        raise ValueError("transaction outside supplied daily history")
    if not 1<=horizon_days<=366 or not 1<=n_paths<=5000 or seed<0:
        raise ValueError("invalid forecast shape/seed")
    for r in history:
        if any(not math.isfinite(r[k]) or r[k]<0 for k in ("inflow","outflow")):
            raise ValueError("invalid daily totals")
        if any(k not in CATEGORIES or not math.isfinite(v) for k,v in r.get("by_category",{}).items()):
            raise ValueError("invalid signed category totals")
    by_date={r["date"]:r for r in history};covered={}
    for tx in projected.transactions:
        if by_date[tx["date"]].get("missing"):
            raise ValueError("transaction on missing history day")
        if tx["category"] not in INTERNAL:
            key=(tx["date"],"inflow" if tx["direction"]=="in" else "outflow")
            covered[key]=covered.get(key,Decimal(0))+money(tx["amount"])
    for (day,side),amount in covered.items():
        if amount>money(by_date[day][side])+Decimal('0.01'):
            raise ValueError("business transactions exceed daily reference totals")
    return message_type(model="structural_m6",company_id=company_id,industry=industry,
        history=history,transactions=list(projected.transactions),horizon_days=horizon_days,n_paths=n_paths,
        seed=seed,flow_scope="business_without_internal_transfers")

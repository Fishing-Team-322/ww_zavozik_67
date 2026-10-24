"""Conservative, local weak supervision for channels and independent tags.

These labels are evidence extracted from text, not human ground truth. Channel
priority denotes the explicitly stated settlement rail (digital ruble wins
over a QR interface). A bank/counterparty name alone never proves a rail.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .taxonomy import Taxonomy
from .text import Operation, VAT_BOILERPLATE
from zavozik_ml.classify.text import _fix_word


def _rx(pattern: str):
    return re.compile(pattern, re.I)


def clean(text: str) -> str:
    text = str(text or "").lower().replace("ё", "е")
    return " ".join(_fix_word(w) for w in text.split())


_DIGITAL = _rx(r"цифров\w*\s+(?:форм\w*\s+)?рубл\w*|\bцр\b|\bцифр\.?\s*руб\w*|\bdigital\s+rubl?e?\b|\be-?rubl?e?\b")
_SBP = _rx(r"\bсбп\b|систем\w*\s+быстр\w*\s+платеж\w*|\bqr\b|\bc2b\b|\bb2b-?qr\b")
_CASH = _rx(r"\bналичн\w*|\bналичк\w*|инкассац\w*|самоинкассац\w*|\bcash[ -]?in\b")
_CARD = _rx(r"эквайр\w*|\bpos\b|карточн\w*\s+(?:покуп\w*|продаж\w*|транзакц\w*|операц\w*|выруч\w*)|"
            r"выручк\w*[^.;]{0,35}(?:банковск\w*\s+)?карт\w*|"
            r"оплат\w*\s+(?:банковск\w*\s+)?картой|\b(?:sberpay|t-pay|mir\s*pay)\b")
_MARKET = _rx(r"маркетплейс\w*|wildberries|вайлдберриз|\bozon\b|озон|яндекс\s*маркет")
_MARKET_PAYOUT = _rx(r"выплат\w*|перечислен\w*|выручк\w*|продавц\w*|реализац\w*|поступлен\w*|продаж\w*")
_BANK_FEE = _rx(r"\bрко\b|расчетно[ -]кассов\w*|(?:комис\w*|вознагражден\w*)[^.;]{0,60}(?:банк\w*|эквайр\w*|перевод\w*|счет\w*|валютн\w*|выдач\w*\s+наличн\w*)|"
                r"плат\w*\s+за\s+(?:ведени\w*\s+(?:расчетн\w*\s+)?счет\w*|обслуживани\w*\s+(?:корпоративн\w*\s+)?карт\w*)")
_INTERNAL_BANK = _rx(r"(?:списан\w*|зачислен\w*)\s+банк\w*|банк\w*\s+(?:списал\w*|удержал\w*|зачислил\w*)")
_BANK_TRANSFER = _rx(r"по\s+реквизит\w*|безналичн\w*|банк[ -]клиент|интернет[ -]банк|платежн\w*\s+поручен\w*|"
                     r"(?:счет\w*|сч\.|упд|акт\w*|договор\w*|требован\w*|лист\w*|постановлен\w*)\s*(?:№|номер|n\b|#|[а-яa-z]-?\d|\d)")
_DOCUMENT = _rx(r"(?:счет\w*|сч\.|упд|договор\w*|дог\.|акт\w*|накладн\w*|лист\w*|требован\w*|постановлен\w*)\s*"
               r"(?:№|номер|n\b|#)?\s*[а-яa-z0-9][а-яa-z0-9/_.-]{0,40}\s+от\s+"
               r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})")
_MONTH = r"(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)"
_TAG_RULES = {
    "prepayment": _rx(r"предоплат\w*|\bаванс\w*|авансов\w*|\bав\.\s"),
    "partial_payment": _rx(r"частичн\w*\s+(?:оплат\w*|платеж\w*|выплат\w*|погашен\w*|возврат\w*|внесен\w*)|част[ьи]\s+оплат\w*"),
    "final_payment": _rx(r"окончательн\w*\s+расчет\w*|\bдоплат\w*|финальн\w*\s+(?:оплат\w*|платеж\w*|расчет\w*)"),
    "budget_payment": _rx(r"казначейств\w*|\bуфк\b|\bифнс\b|\bфнс\b|\bсфр\b|\bенп\b|\bенс\b|\bндфл\b|\bусн\b|"
                           r"\bналог\w*|страхов\w*\s+взнос\w*|взнос\w*\s+на\s+травматизм|госпошлин\w*|государственн\w*\s+пошлин\w*|"
                           r"\bндс\b|перечислен\w*\s+в\s+бюджет"),
    "owner_money": _rx(r"собственн\w*\s+(?:денежн\w*\s+)?средств\w*|собств\.\s*средств\w*|между\s+своими|"
                        r"(?:свой|своего|собственн\w*)\s+(?:кошелек|кошельк\w*|счет\w*)|"
                        r"личн\w*\s+(?:счет\w*|карт\w*|кошел\w*)|учредител\w*|участник\w*|уставн\w*\s+капитал|дивиденд\w*|"
                        r"остатк\w*[^.;]{0,60}закрыти\w*\s+счет\w*"),
    "refund": _rx(r"возврат\w*|\bвозвр\.|возмещен\w*\s+покупател\w*"),
    "recurring_like": _rx(r"ежемесячн\w*|регулярн\w*|\bза\s+" + _MONTH + r"\b|аванс\w*\s+по\s+(?:зарплат\w*|заработн\w*\s+плат\w*)"),
    "with_document": _DOCUMENT,
    "enforcement": _rx(r"исполнительн\w*\s+(?:лист\w*|производств\w*|документ\w*)|\bисп\.\s*лист\w*|"
                        r"инкассов\w*\s+поручен\w*|судебн\w*\s+(?:приказ\w*|пристав\w*)|\bфссп\b|постановлен\w*\s+пристав\w*"),
}


@dataclass(frozen=True)
class WeakLabels:
    channel: str
    tags: tuple[str, ...]
    source: str = "text_regex_v2.3_weak_not_gold"


def annotate(op: Operation, taxonomy: Taxonomy | None = None) -> WeakLabels:
    p, n = clean(op.purpose), clean(op.counterparty_name)
    text = f"{p} {n}"
    if _DIGITAL.search(p):
        channel = "digital_ruble"
    elif _SBP.search(p):
        channel = "sbp"
    elif op.direction == "in" and _CARD.search(p):
        # The payout is still acquiring when its description mentions the
        # bank's deducted commission. That fee is not this operation's rail.
        channel = "card_acquiring"
    elif _BANK_FEE.search(p) or _INTERNAL_BANK.search(p):
        channel = "internal_bank"
    elif _CASH.search(p):
        channel = "cash"
    elif _CARD.search(p):
        channel = "card_acquiring"
    elif op.direction == "in" and _MARKET.search(text) and _MARKET_PAYOUT.search(p):
        channel = "marketplace_payout"
    elif _BANK_TRANSFER.search(p):
        channel = "bank_transfer"
    else:
        channel = "unknown"
    # Counterparty identity is evidence only for budget/owner/enforcement tags;
    # a generic bank or marketplace does not imply any economic category.
    # "Без налога (НДС)" / "в том числе НДС" are invoice boilerplate, not
    # evidence of remittance to the treasury. Keep actual "НДС за квартал".
    evidence = {"budget_payment": VAT_BOILERPLATE.sub(" ", text), "owner_money": text, "enforcement": text}
    tags = tuple(k for k, rx in _TAG_RULES.items() if rx.search(evidence.get(k, p)))
    # Returning a loan / tax overpayment is not a commercial refund tag. The
    # refund axis denotes customer/supplier refunds, not every use of the verb.
    if "refund" in tags and re.search(r"возврат\w*\s+(?:(?:беспроцентн\w*|остатк\w*\s+собственн\w*)\s+)?(?:займ\w*|заем\w*|основн\w*\s+долг\w*)|"
                                     r"возврат\w*\s+остатк\w*\s+(?:с\s+)?собственн\w*", p):
        tags = tuple(t for t in tags if t != "refund")
    if taxonomy is not None:
        if channel not in taxonomy.channels:
            channel = "unknown" if "unknown" in taxonomy.channels else taxonomy.channels[-1]
        tags = tuple(t for t in tags if t in taxonomy.tags)
    return WeakLabels(channel, tags)

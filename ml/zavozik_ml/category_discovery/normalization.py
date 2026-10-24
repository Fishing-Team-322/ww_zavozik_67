"""Versioned discovery text; never changes the sealed v1 encoder contract.

No categories or economic-object dictionaries. Numbers identifying goods,
negation and financial roles survive; only explicitly marked metadata is
removed. This is text cleanup, not an economic classifier.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from decimal import Decimal
import re
import unicodedata

from zavozik_ml.classify.text import _fix_word

TEXT_VERSION = "purpose_evidence_query_v2"
_NUMBER = r"\d+(?:[ \u00a0]\d{3})*(?:[.,-]\d{1,2})?"
_CURRENCY = r"(?:руб(?:лей|ля|ль)?\.?|р\.|₽|коп(?:еек|ейки)?\.?)"
_DATE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})(?:\s*г\.?)?(?!\d)")
_MONTH = r"(?:(?:январ|феврал|март|апрел|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*|ма[йя])"
_VAT = re.compile(
    r"\b(?:без\s+(?:налога\s*)?\(?ндс\)?|ндс\s+не\s+облагается)"
    r"|\b(?:(?:в\s+т\.?\s*ч\.?|в\s+том\s+числе)\s*[,;:]?\s*)?ндс\s*"
    r"(?:\(?\d+(?:[.,]\d+)?\s*%\)?(?:\s*[-:=]?\s*" + _NUMBER + r")?"
    r"|[:=]\s*" + _NUMBER + r")(?:\s*" + _CURRENCY + r")?"
)
_DOC_ID = re.compile(r"(?:№|\bномер\b|#)\s*[a-zа-я0-9][a-zа-я0-9/._-]*")
_MARKED_MONEY = re.compile(r"\bсумм[аы]\s*[:=]?\s*" + _NUMBER + r"(?:\s*" + _CURRENCY + r")?")
_MONEY = re.compile(r"\b" + _NUMBER + r"\s*" + _CURRENCY + r"(?![а-яa-z])")
_FINANCIAL_COMPONENT = re.compile(r"\b(сумма\s+операций|сумма\s+платежа|сумма\s+перевода|основной\s+долг|проценты|комиссия|возврат\s+покупки|всего)\s*[:=]?\s*(" + _NUMBER + r")(?:\s*" + _CURRENCY + r")?")
_STAGE = re.compile(r"\b(?:окончательн[а-я]*|частичн[а-я]*|предварительн[а-я]*)\s+(?:оплата|оплаты|платеж|расчет)\b|\bпредоплата\b")
_CHANNEL = re.compile(r"\b(?:через|посредством)\s+(?:сбп|систему\s+быстрых\s+платежей|интернет[ -]банк|банк[ -]клиент)\b|\b(?:в\s+)?цифров[а-я]*\s+(?:форм[а-я]*\s+)?рубл[а-я]*\b|\bпо\s+qr[ -]коду\b")
_GENERIC = frozenset("оплата оплаты платеж платежа платежи перечисление перечисления поступление списание назначение указано неизвестно средства средств денежных денежные за по на от и в с из для согласно расчет расчета расчеты аванс аванса частичная окончательный предварительная без назначения не указан нет данных договор договору договора счет счету счета акту акт упд накладной накладная реестр реестру период года год г мес месяц".split())


@dataclass(frozen=True)
class PurposeView:
    semantic_text: str
    information: str
    stages: tuple[str, ...]
    channels: tuple[str, ...]
    text_version: str = TEXT_VERSION

    @property
    def usable(self):
        return self.information == "has_object_or_role"

    def document(self):
        return dict(asdict(self), usable=self.usable)


def analyze(purpose: str) -> PurposeView:
    # Protect № before NFKC expands it to No; English 'no refund' is negation,
    # never a document identifier.
    s = unicodedata.normalize("NFKC", str(purpose or "").replace("№", " __docnumber__ ")).lower().replace("ё", "е")
    s = s.replace("__docnumber__", "№")
    s = " ".join(_fix_word(w) for w in s.split())
    stages = tuple(sorted(set(m.group() for m in _STAGE.finditer(s))))
    channels = tuple(sorted(set(m.group() for m in _CHANNEL.finditer(s))))
    s = _VAT.sub(" ", s)
    s = re.sub(r"\bот\s+(?=" + _DATE.pattern + r")", " ", s)
    s = _DATE.sub(" ", s)
    s = _DOC_ID.sub(" ", s)
    s = re.sub(r"\b(лицев(?:ому|ой)\s+счет[уа]?|расчетн(?:ый|ому)\s+счет[уа]?|инн|кпп|бик)\s*[:=]?\s*\d+[\d -]*", r"\1 ", s)
    # Bare numeric references occur without № too. Only document contexts,
    # never 'на счет ...' (account role) or product specifications.
    s = re.sub(r"\b(?:по|согласно)\s+(?:счету|счет|сч\.?|договору|договор|дог\.?|упд|акту|накладной)\s+[0-9][a-zа-я0-9/._-]*", " ", s)
    def component(m):
        value = Decimal(re.sub(r"\s", "", m[2]).replace(",", ".").replace("-", "."))
        # A zero refund in an acquiring summary is NOT a refund event.
        return " " if not value or m[1].startswith(("сумма", "всего")) else " " + m[1] + " "
    s = _FINANCIAL_COMPONENT.sub(component, s)
    s = _MARKED_MONEY.sub(" ", s)
    s = _MONEY.sub(" ", s)
    s = re.sub(r"\bдата\s+реестра\b", " ", s)
    s = re.sub(r"\b\d+\s*(?:дн\.?|дней)\b", " ", s)
    s = re.sub(r"\bза\s+[1-4]\s+квартал(?:а)?\b", " ", s)
    s = re.sub(r"\b(?:за|за период|в период|период)\s+" + _MONTH + r"(?:\s+\d{4})?(?:\s*г(?:ода)?\.?)?\b", " ", s)
    s = re.sub(r"\b\d{4}\s*г(?:ода)?\.?\b", " ", s)
    s = _CHANNEL.sub(" ", s)
    s = _STAGE.sub("оплата", s)
    # A bare document reference has no object. Never consume adjectival
    # continuation: 'по договору кредитной линии' must retain credit role.
    s = re.sub(r"\b(?:по|согласно)\s+(?:договору|счету|упд|акту|накладной)\b(?=\s*(?:от\b|[.;,:]|$))", " ", s)
    tokens = re.findall(r"[а-яa-z0-9]+", s)
    while tokens and tokens[-1] in {"от", "по", "за", "на", "с", "г", "года"}:
        tokens.pop()
    text = " ".join(tokens)
    content = [w for w in tokens if re.search(r"[а-яa-z]", w) and w not in _GENERIC]
    information = "has_object_or_role" if content else ("generic_payment" if tokens else "empty")
    return PurposeView(text, information, stages, channels)


def semantic_text(purpose: str) -> str:
    return analyze(purpose).semantic_text


def embedding_text(purpose: str) -> str:
    return "query: " + semantic_text(purpose)


def content_key(direction: str, purpose: str) -> str:
    if direction not in ("in", "out"):
        raise ValueError("invalid direction")
    return "content-" + hashlib.sha256((direction + "\0" + semantic_text(purpose)).encode()).hexdigest()[:24]

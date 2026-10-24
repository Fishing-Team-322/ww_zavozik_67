"""Shared train/runtime text contract. No INN digits enter the encoder."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from zavozik_ml.classify.text import (
    Op, _DATE, _MONTHS, _MONEY, _NUM, _VAT, _WORD, _fix_word,
    counterparty_type, norm_direction,
)

NORMALIZER_VERSION = "v2-preserve-payment-channel-1"
_LEGAL = re.compile(r"\b(?:ооо|оао|зао|пао|ао|ип|нко|ано|муп|гуп|фгуп)\b")


@dataclass(frozen=True)
class Operation:
    direction: str
    purpose: str = ""
    counterparty_name: str = ""
    counterparty_type: str = "none"
    amount: float = 0.0
    id: str = ""

    @classmethod
    def from_legacy(cls, op: Op, id: str = "") -> "Operation":
        return cls(op.direction, op.purpose, op.counterparty_name,
                   counterparty_type(op.counterparty_inn), op.amount, id)


def normalize(text: str) -> str:
    """Same substitutions as v1 except digital-ruble mentions are preserved."""
    s = str(text or "").lower().replace("ё", "е")
    s = " ".join(_fix_word(w) for w in s.split())
    s = _VAT.sub(" ", s)
    s = _MONTHS.sub(" мес ", s)
    s = _DATE.sub(" дата ", s)
    s = _MONEY.sub(" сумма ", s)
    s = s.replace("%", " процент ").replace("№", " номер ")
    s = _NUM.sub(" 0 ", s)
    return " ".join(_WORD.findall(s))


def amount_bucket(amount: float) -> str:
    try:
        a = abs(float(amount))
    except (TypeError, ValueError, OverflowError):
        return "неизвестна"
    if not math.isfinite(a) or a <= 0:
        return "неизвестна"
    return str(min(int(math.log10(a + 1) * 2), 16))


def encoder_text(op: Operation) -> str:
    d = {"in": "поступление", "out": "списание"}.get(norm_direction(op.direction), "неизвестно")
    ct = {"org": "организация", "person": "ип физлицо", "none": "пусто", "bad": "неизвестно"}.get(
        op.counterparty_type, "неизвестно")
    name = " ".join(_LEGAL.sub(" ", normalize(op.counterparty_name)).split())[:160]
    purpose = normalize(op.purpose)
    return (f"направление {d}. контрагент {ct} {name or 'не указан'}. "
            f"назначение {purpose or 'не указано'}. сумма бакет {amount_bucket(op.amount)}")


def dedupe_key(op: Operation) -> tuple[str, str, str]:
    """Collapse repeated purpose templates, including document/date/amount slots.

    Name and amount are deliberately excluded. Empty purpose retains the name,
    since removing it would merge economically different operations.
    """
    p = normalize(op.purpose)
    return norm_direction(op.direction), p, normalize(op.counterparty_name) if not p else ""

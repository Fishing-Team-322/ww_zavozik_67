"""Нормализация текста операции и признаки для классификатора.

Один и тот же код — в обучении и в сервинге. Признаки — хэшированные
(zlib.crc32, стабилен между процессами и версиями Python), поэтому словарь
хранить не нужно.

Принципы:
- регистр, «ё», латинские буквы-двойники в русских словах, номера, даты,
  суммы и месяцы приводим к единому виду — модель видит смысл, а не реквизиты;
- упоминание цифрового рубля убираем из текста совсем: это обычные рубли,
  способ платежа не меняет экономический смысл операции;
- хвосты про НДС убираем — они есть во всех категориях;
- текстовые признаки дублируем в паре с направлением: «оплата по УПД»
  у поступления — выручка, у списания — поставщик.
"""

from __future__ import annotations

import math
import re
import zlib
from dataclasses import dataclass

N_FEATURES = 1 << 18

# Порядок совпадает с domain.AllCategories в Go и enum Category в api/openapi.yaml.
CATEGORIES: tuple[str, ...] = (
    "revenue_acquiring", "revenue_sbp", "revenue_cash", "revenue_b2b", "revenue_marketplace",
    "supplier", "salary", "tax", "rent", "utilities", "loan_payment", "leasing",
    "bank_fee", "marketing", "services", "own_transfer", "owner_loan", "refund",
    "enforcement", "other",
)
OTHER = "other"


@dataclass(frozen=True)
class Op:
    """Операция на входе классификатора. ИНН в признаки не идёт — только его тип."""

    direction: str  # "in" | "out" (принимаем и «Поступление»/«Списание»)
    purpose: str = ""
    counterparty_name: str = ""
    counterparty_inn: str = ""
    amount: float = 0.0


def norm_direction(d: str) -> str:
    d = (d or "").strip().lower()
    if d in ("in", "поступление", "приход", "credit", "+"):
        return "in"
    if d in ("out", "списание", "расход", "debit", "-"):
        return "out"
    return "unk"


def counterparty_type(inn: str) -> str:
    """10 цифр — организация, 12 — ИП/физлицо, пусто — нет, иначе — мусор."""
    s = re.sub(r"\D", "", inn or "")
    if not s:
        return "none"
    if len(s) == 10:
        return "org"
    if len(s) == 12:
        return "person"
    return "bad"


# Латинские буквы, похожие на кириллические: «Oплата» с латинской O.
_LAT2CYR = str.maketrans("aceopxykmhtb", "асеорхукмнтв")
_HAS_CYR = re.compile(r"[а-я]")
_WORD = re.compile(r"[a-zа-я0-9]+")

_MONTHS = re.compile(
    r"\b(?:(?:январ|феврал|март|апрел|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*|ма[йя])\b"
)
# Цифровой рубль (и его сокращения) — способ платежа, а не смысл: убираем.
_DIGITAL_RUBLE = re.compile(
    r"(в\s+)?цифров[а-я]*\s+(форм[а-я]*\s+)?рубл[а-я]*"
    r"|цифров[а-я]*\s+валют[а-я]*(\s+(цб|банка\s+россии)(\s+рф)?)?"
    r"|\bцр\b|\bцифр\.?\s*руб[а-я.]*"
    r"|\be-?rub(le)?\b|\bdigital\s+rub(le)?\b"
)
_VAT = re.compile(
    r"(в\s+т\.?\s*ч\.?|в\s+том\s+числе)\s*ндс[^.;]*"
    r"|ндс\s+не\s+облагается|без\s+налога\s*\(?ндс\)?|без\s+ндс|ндс\s+\d+\s*%[^.;]*"
)
_DATE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(\s*г\.?)?(?!\d)|\b\d{4}-\d{2}-\d{2}\b")
_MONEY = re.compile(r"\b\d{1,3}(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})(?!\d)|\b\d+[.,]\d{2}(?!\d)")
_NUM = re.compile(r"\d+")
_LEGAL = re.compile(r"\b(ооо|оао|зао|пао|ао|ип|нко|ано|муп|гуп|фгуп|ано\s+дпо)\b")


def _fix_word(w: str) -> str:
    # Латиницу в словах с кириллицей меняем на кириллицу; чисто латинские слова
    # (SberPay, QR, Ozon) не трогаем.
    if _HAS_CYR.search(w) and re.search(r"[a-z]", w):
        return w.translate(_LAT2CYR)
    return w


def normalize(text: str) -> str:
    """Канонический вид назначения платежа (или названия)."""
    if not text:
        return ""
    s = str(text).lower().replace("ё", "е")
    s = " ".join(_fix_word(w) for w in s.split())
    s = _DIGITAL_RUBLE.sub(" ", s)
    s = _VAT.sub(" ", s)
    s = _MONTHS.sub(" мес ", s)
    s = _DATE.sub(" дата ", s)
    s = _MONEY.sub(" сумма ", s)
    s = s.replace("%", " процент ")
    s = s.replace("№", " номер ")
    s = _NUM.sub(" 0 ", s)
    toks: list[str] = []
    for t in _WORD.findall(s):
        if not (toks and t in ("0", "сумма") and toks[-1] == t):
            toks.append(t)
    return " ".join(toks)


def normalize_name(name: str) -> str:
    s = normalize(name)
    s = _LEGAL.sub(" ", s)
    return " ".join(s.split())


def _h(s: str) -> int:
    return zlib.crc32(s.encode("utf-8")) & (N_FEATURES - 1)


def _char_ngrams(text: str, lo: int = 3, hi: int = 5) -> list[str]:
    out = []
    for w in text.split():
        if w == "0":
            continue
        w = f" {w} "
        for n in range(lo, hi + 1):
            if len(w) < n:
                if n == lo:
                    out.append(w)
                break
            out.extend(w[i:i + n] for i in range(len(w) - n + 1))
    return out


def _words(text: str) -> list[str]:
    toks = text.split()
    return toks + [a + "_" + b for a, b in zip(toks, toks[1:])]


def _amount_bucket(amount: float) -> str:
    try:
        a = abs(float(amount))
    except (TypeError, ValueError):
        return "na"
    if not math.isfinite(a) or a <= 0:
        return "na"
    return str(min(int(math.log10(a + 1) * 2), 16))  # полудекады: 1–3, 3–10, 10–30 ...


# Веса блоков признаков: текст назначения важнее названия, мета — подсказка.
BLOCK_WEIGHTS = {"p": 1.0, "n": 0.6, "m": 0.5}


def features(op: Op) -> tuple[list[int], list[float]]:
    """Хэшированные признаки операции: индексы и значения (каждый блок L2-нормирован)."""
    d = norm_direction(op.direction)
    purpose = normalize(op.purpose)
    name = normalize_name(op.counterparty_name)
    ctype = counterparty_type(op.counterparty_inn)
    amt = _amount_bucket(op.amount)

    blocks: dict[str, list[str]] = {"p": [], "n": [], "m": []}
    pw, pc = _words(purpose), _char_ngrams(purpose)
    blocks["p"] = (["w:" + t for t in pw] + ["c:" + t for t in pc]
                   + [f"dw:{d}:" + t for t in pw] + [f"dc:{d}:" + t for t in pc])
    nw, nc = _words(name), _char_ngrams(name)
    blocks["n"] = (["nw:" + t for t in nw] + ["nc:" + t for t in nc]
                   + [f"dnw:{d}:" + t for t in nw] + [f"dnc:{d}:" + t for t in nc])
    empty_p = "1" if not purpose else "0"
    empty_n = "1" if not name else "0"
    blocks["m"] = [
        "bias", f"dir:{d}", f"ct:{ctype}", f"dct:{d}:{ctype}", f"amt:{amt}", f"damt:{d}:{amt}",
        f"ep:{empty_p}", f"dep:{d}:{empty_p}", f"en:{empty_n}", f"dctep:{d}:{ctype}:{empty_p}",
    ]

    acc: dict[int, float] = {}
    for b, toks in blocks.items():
        if not toks:
            continue
        local: dict[int, float] = {}
        for t in toks:
            i = _h(b + "|" + t)
            local[i] = local.get(i, 0.0) + 1.0
        norm = math.sqrt(sum(v * v for v in local.values())) or 1.0
        w = BLOCK_WEIGHTS[b] / norm
        for i, v in local.items():
            acc[i] = acc.get(i, 0.0) + v * w
    idx = list(acc.keys())
    return idx, [acc[i] for i in idx]


def cache_key(op: Op) -> tuple:
    """Ключ дедупликации: операции с одинаковым ключом дают одинаковые признаки."""
    return (norm_direction(op.direction), normalize(op.purpose), normalize_name(op.counterparty_name),
            counterparty_type(op.counterparty_inn), _amount_bucket(op.amount))

"""Слабые метки для обучения: правила Go + ручная доразметка шаблонов.

1. Основа — метки ровно тех правил, что в проде (`categorize.DefaultRules`),
   выгруженные из Go командой `backend/cmd/rulelabel`. Повторять правила в
   Python не стали, чтобы не было расхождений.
2. Где правила дали `other`, применяем `EXTRA_RULES` — ручная разметка всех
   шаблонов назначений датасета, которые правила не покрыли (шаблоны
   просмотрены целиком, решения по спорным — в ml/reports/classifier.md).
3. `FIXES` — известные ошибки правил (например, «в связи с закрытием счета»
   попадало в utilities из-за слова «связи»).
4. Пустое назначение: если контрагент почти всегда (≥ 90%) встречается
   с одной категорией в размеченных строках, берём её (кроме банка —
   у него десяток разных категорий).
То, что после этого осталось `other`, — действительно неопределимые операции.
"""

from __future__ import annotations

import re
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .text import CATEGORIES, normalize_name


@dataclass(frozen=True)
class Rule:
    category: str
    direction: str | None  # "in" | "out" | None — любое
    purpose: str | None = None
    name: str | None = None

    def compile(self):
        return (
            self.category,
            self.direction,
            re.compile(self.purpose, re.I) if self.purpose else None,
            re.compile(self.name, re.I) if self.name else None,
        )


_GOODS = (
    r"товар|продук|материал|издели|напитк|бакале|запчаст|автохими|хими|семен|удобрен|средства защиты|"
    r"металлопрокат|бетон|инструмент|фурнитур|оборудован|одежд|обув|пиломатериал|лкм|метиз|лдсп|упаковк|"
    r"косметик|игрушк|детские товары|шин[ыа]\b|масла|техжидкост|бель[её]|трикотаж|канцтовар|хозтовар|"
    r"хозяйственн|кофе|аксессуар|автомобил|овощ|фрукт|расходн|медицинские|топлив"
)

# Только для строк, где правила Go дали other. Порядок важен.
EXTRA_RULES: list[Rule] = [
    Rule("owner_loan", "in", r"займ|заем|уставный капитал|погашения задолженности по овердрафту", r"учредител|участник"),
    Rule("owner_loan", "in", r"займ.*(учредител|участник)|уставный капитал"),
    Rule("own_transfer", "out", r"дивиденд|на личный счет предпринимател|на личную карту"),
    Rule("loan_payment", "out", r"основного долга|кредитной линии|процентов по договору кредит|по кредиту"),
    Rule("loan_payment", "in", r"выдача кредита|кредит\w* лини|транш"),
    Rule("revenue_marketplace", "in", r"агентск\w+ договор\w*.*(проживан|бронир|заказ)", r"бронирован|агрегатор"),
    Rule("revenue_b2b", "in", r"авансов\w* платеж|по договору подряда|оплата|предоплата|аванс"),
    Rule("other", "in", r"субсиди|грант|страхов\w* возмещен"),
    Rule("services", "out", r"права использования|подписк|лицензи|субподряд|выполненные работы|подряд|ремонт|"
                            r"шиномонтаж|обслуживан|лабораторн|исследован|зуботехнич|провоз|расчетной записи"),
    Rule("supplier", "out", r"\bза\b[^.]{0,40}(" + _GOODS + r")|пополнение лицевого счета.*топлив|купли-продажи"),
]

FIXES: list[Rule] = [
    Rule("own_transfer", None, r"в связи с закрытием счета"),
]

_BANK_NAME = re.compile(r"банк", re.I)


def _apply(rules: list[Rule], direction: str, purpose: str, name: str) -> str | None:
    for r in rules:
        cat, d, pre, nre = r.compile()
        if d and d != direction:
            continue
        p_ok = pre is None or bool(pre.search(purpose))
        n_ok = nre is None or bool(nre.search(name))
        if (pre is not None or nre is not None) and p_ok and n_ok:
            return cat
    return None


def go_rule_labels(csv_path: Path, repo_root: Path, out_path: Path) -> pd.DataFrame:
    """Метки правил Go для CSV (см. backend/cmd/rulelabel). Кэш в out_path."""
    csv_path, out_path = Path(csv_path).resolve(), Path(out_path).resolve()
    signature = hashlib.sha256(csv_path.read_bytes())
    for path in sorted((repo_root / "backend/internal/categorize").glob("*.go")):
        if not path.name.endswith("_test.go"):
            signature.update(path.read_bytes())
    signature.update((repo_root / "backend/cmd/rulelabel/main.go").read_bytes())
    expected = {"source": str(csv_path), "sha256": signature.hexdigest()}
    meta = out_path.with_suffix(out_path.suffix+".metadata.json")
    try:
        valid = json.loads(meta.read_text()) == expected
    except (OSError, ValueError):
        valid = False
    if not out_path.exists() or not valid:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["go", "run", "./cmd/rulelabel", "-in", str(csv_path), "-out", str(out_path)],
            cwd=repo_root / "backend", check=True,
        )
        meta.write_text(json.dumps(expected))
    return pd.read_csv(out_path, sep=";", dtype={"id": str, "category": str})


def load_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype={"counterparty_inn": str, "operation_id": str})
    df["counterparty_inn"] = df["counterparty_inn"].fillna("")
    df["counterparty_name"] = df["counterparty_name"].fillna("")
    df["payment_purpose"] = df["payment_purpose"].fillna("")
    df["direction"] = df["direction"].map({"Поступление": "in", "Списание": "out"})
    return df


def teacher_labels(df: pd.DataFrame, go: pd.DataFrame) -> pd.DataFrame:
    """Добавляет к датасету колонки rule (Go) и label (учитель для обучения)."""
    go = go.rename(columns={"id": "operation_id", "category": "rule"})[["operation_id", "rule"]]
    out = df.merge(go, on="operation_id", how="left", validate="one_to_one")
    if out["rule"].isna().any():
        raise ValueError("нет меток Go для части операций")

    labels = []
    for d, p, n, r in zip(out.direction, out.payment_purpose, out.counterparty_name, out.rule):
        fixed = _apply(FIXES, d, p, n)
        if fixed:
            labels.append(fixed)
        elif r == "other":
            labels.append(_apply(EXTRA_RULES, d, p, n) or "other")
        else:
            labels.append(r)
    out["label"] = labels

    # Пустое назначение — по устойчивой категории контрагента.
    key = out.counterparty_name.map(normalize_name) + "|" + out.direction
    known = out[(out.payment_purpose.str.strip() != "") & (out.label != "other")]
    top = known.groupby(key[known.index]).label.agg(lambda s: s.value_counts().index[0])
    share = known.groupby(key[known.index]).label.agg(lambda s: s.value_counts(normalize=True).iloc[0])
    empty = (out.payment_purpose.str.strip() == "") & (out.label == "other") & ~out.counterparty_name.str.contains(_BANK_NAME)
    for i in out.index[empty]:
        k = key[i]
        if k in share.index and share[k] >= 0.9:
            out.at[i, "label"] = top[k]
    assert set(out.label) <= set(CATEGORIES)
    return out


def teacher_label_partitions(partitions: dict[str, pd.DataFrame], go: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Infer missing-purpose labels within each split, never across its boundary.

    Counterparty majority labels depend on data, unlike the fixed regex rules.
    Constructing them on the full dataset before splitting can leak test rows
    into training targets. Test labels are still weak labels, not human gold.
    """
    seen: set[str] = set()
    result = {}
    for name, part in partitions.items():
        ids = set(part.operation_id)
        if seen & ids:
            raise ValueError("operation appears in multiple classifier partitions")
        seen.update(ids)
        result[name] = teacher_labels(part, go)
    return result

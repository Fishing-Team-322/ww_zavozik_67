"""OPEN authored development contrasts, NOT independent semantic validation.

Expectations are agent-authored, exposed before running candidates. They cover
known failure mechanisms and cannot select a production model or calibrate a
quality claim. There are no category IDs and no fixed output vocabulary.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from zavozik_ml.classify_v2.model import sha256_file
from .candidate_models import CandidateEncoder
from .normalization import analyze

# (ID, relation level, anchor, same-relation paraphrase, economic contrast)
CASES = (
    ("salary_land_rent", "coarse", "Выплата заработной платы сотрудникам", "Вознаграждение работников за труд", "Перечисление арендной платы за земельные паи"),
    ("credit_subsidy", "coarse", "Получение заемных средств от банка", "Банк перечислил кредитный транш", "Получение бюджетной субсидии на проведение полевых работ"),
    ("own_transfer_salary", "coarse", "Перевод собственных средств между расчетными счетами компании", "Перемещение денег организации на ее другой счет", "Выплата заработной платы сотрудникам"),
    ("debt_service_asset", "coarse", "Погашение основного долга по кредиту", "Уплата процентов за пользование кредитом", "Оплата за покупку оборудования"),
    ("principal_interest", "fine", "Погашение основного долга по кредиту", "Возврат тела банковского кредита", "Уплата процентов за пользование кредитом"),
    ("vehicle_autochemistry", "fine", "Оплата за автомобиль", "Покупка транспортного средства", "Оплата за автохимию"),
    ("bedding_furniture_hardware", "fine", "Оплата за постельные принадлежности", "Покупка постельного белья", "Оплата за мебельную фурнитуру"),
    ("website_medicine", "fine", "Оплата за доработку сайта", "Разработка и изменение веб сайта", "Покупка лекарственных препаратов"),
    ("cargo_medicine", "fine", "Оплата услуг перевозки груза", "Расчеты за транспортировку товаров", "Покупка лекарственных препаратов"),
    ("land_rent_salary", "coarse", "Перечисление арендной платы за земельные паи", "Плата за пользование арендованным земельным участком", "Перечисление заработной платы по реестру"),
    ("loan_goods_refund", "coarse", "Возврат суммы займа", "Погашение заемных средств", "Возврат покупателю денег за непоставленный товар"),
    ("dividend_salary", "coarse", "Выплата дивидендов участнику общества", "Распределение прибыли между собственниками", "Выплата заработной платы сотрудникам"),
    ("vat_tax_object", "fine", "Уплата НДС за квартал", "Перечисление налога на добавленную стоимость", "Оплата за консультационные услуги. В т.ч. НДС 20% 1000,00 руб."),
    ("rent_purchase", "coarse", "Оплата аренды оборудования", "Плата за временное пользование оборудованием", "Оплата за покупку оборудования"),
)


def run(model, base: Path, out: Path, device="cpu"):
    if out.exists():
        raise ValueError("regression run exists")
    views = [[analyze(t) for t in case[2:]] for case in CASES]
    if not all(v.usable for vs in views for v in vs):
        raise ValueError("authored economic contrast lost its object")
    encoder = CandidateEncoder(model, base, device=device)
    out.mkdir(parents=True)
    report = dict(model=model, recipe=asdict(encoder.spec), source="agent_authored_open_development_regressions",
                  independent_test=False, semantic_accuracy=None, category_inventory="not_used",
                  purpose="Known-error debugging only; not model/threshold selection or real-world accuracy",
                  code_sha256=sha256_file(Path(__file__)), base=encoder.source, device=device)
    (out / "started.json").write_text(json.dumps(report, indent=2) + "\n")
    started = time.perf_counter()
    x = encoder([v.semantic_text for vs in views for v in vs])
    report["seconds"] = time.perf_counter()-started
    results = []
    for i, (identity, level, anchor, positive, negative) in enumerate(CASES):
        a, p, n = x[i*3:i*3+3]
        pos, neg = float(a @ p), float(a @ n)
        results.append(dict(id=identity, level=level, anchor=anchor, positive=positive, negative=negative,
                            positive_cosine=pos, negative_cosine=neg, ranking_margin=pos-neg,
                            expected_order_observed=pos > neg))
    report["cases"] = results
    report["expected_order_count"] = sum(r["expected_order_observed"] for r in results)
    report["total_open_development_contrasts"] = len(results)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    a = p.parse_args()
    print(json.dumps(run(a.model, a.base, a.out, a.device), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

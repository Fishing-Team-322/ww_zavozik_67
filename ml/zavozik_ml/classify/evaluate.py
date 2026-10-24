"""Оценка классификатора против правил Go и генерация ml/reports/classifier.md.

    cd ml && PYTHONPATH=gen:. python -m zavozik_ml.classify.evaluate   # novel_test.csv на артефакте

Наборы:
- holdout — операции отложенных компаний датасета (модель их не видела);
  эталон — метки «учителя» (правила Go + ручная доразметка шаблонов);
- novel — novel_test.csv: вручную составленные назначения, которых нет
  в датасете (новые каналы, цифровой рубль, перефразировки, опечатки...);
- dev — зашумлённые операции отложенных компаний + синтетика (на нём
  подбирались только температура и порог; ориентир, а не главная метрика).
«chain» — прежняя цепочка правил; «hybrid» — opt-in Go Hybrid с порогом 0.8.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from . import labels
from .model import DEFAULT_DIR, Classifier
from .text import CATEGORIES, OTHER, Op

NOVEL = Path(__file__).with_name("novel_test.csv")
# Каналы из novel_test.csv, которых нарочно нет в словарях аугментации.
UNSEEN_CHANNELS = ["долями", "kassa", "биометри", "t-pay", "стикер", "cash-in", "диадок", "мой налог",
                   "смарт-контракт", "платон", "госуслуг", "сплит"]
ML_DIR = Path(__file__).resolve().parents[2]


def scores(y_true, y_pred, amount=None) -> dict:
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    acc = float((y_true == y_pred).mean()) if len(y_true) else float("nan")
    f1s = {}
    for c in sorted(set(y_true) | set(y_pred)):
        tp = int(((y_true == c) & (y_pred == c)).sum())
        fp = int(((y_true != c) & (y_pred == c)).sum())
        fn = int(((y_true == c) & (y_pred != c)).sum())
        f1s[c] = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0
    out = dict(n=len(y_true), accuracy=acc, macro_f1=float(np.mean(list(f1s.values()))) if f1s else float("nan"), f1=f1s)
    if amount is not None:
        a = np.asarray(amount, dtype=float)
        out["turnover_accuracy"] = float(a[y_true == y_pred].sum() / a.sum())
        out["other_turnover_share"] = float(a[y_pred == OTHER].sum() / a.sum())
    return out


def hybrid_predictions(rule, model, confidence, threshold=.8):
    """Same policy as Go Hybrid for default rules, without manual labels."""
    return [m if (m != OTHER and c >= threshold) or r == OTHER else r
            for r, m, c in zip(rule, model, confidence)]


def confidence_metrics(y, predictions, confidence):
    correct = np.asarray(y) == np.asarray(predictions)
    conf = np.asarray(confidence)
    from zavozik_ml.eval.backtest import calibration_error
    return {"ece": calibration_error(conf, correct),
            "confident_errors": int(((conf >= .8) & ~correct).sum()),
            "accepted_fraction": float((conf >= .8).mean()),
            "accepted_accuracy": float(correct[conf >= .8].mean()) if (conf >= .8).any() else float("nan")}


def predict_rows(clf: Classifier, rows: list[dict]) -> tuple[list[str], list[float]]:
    from .train import to_op
    pr = clf.predict([to_op(r) for r in rows])
    return [p.category for p in pr], [p.confidence for p in pr]


def holdout(clf: Classifier, ho_df: pd.DataFrame, ho_rows: list[dict]) -> dict:
    model, conf = predict_rows(clf, ho_rows)
    rule = ho_df.rule.tolist()
    chain = [r if r != OTHER else m for r, m in zip(rule, model)]
    hybrid = hybrid_predictions(rule, model, conf)
    y, a = ho_df.label.tolist(), ho_df.amount.to_numpy()
    confident = ho_df.rule.to_numpy() != OTHER
    agree = float((np.asarray(model)[confident] == ho_df.rule.to_numpy()[confident]).mean())
    res = dict(rules=scores(y, rule, a), model=scores(y, model, a), chain=scores(y, chain, a), hybrid=scores(y, hybrid, a),
               confidence=confidence_metrics(y, model, conf),
               agree_with_go_confident=agree, n_rule_other=int((~confident).sum()))
    res["summary"] = dict(n=len(y), rules_acc=res["rules"]["accuracy"], model_acc=res["model"]["accuracy"],
                          chain_acc=res["chain"]["accuracy"], rules_f1=res["rules"]["macro_f1"],
                          model_f1=res["model"]["macro_f1"], chain_f1=res["chain"]["macro_f1"])
    errs = Counter((t, p) for t, p in zip(y, model) if t != p)
    res["top_errors"] = errs.most_common(12)
    return res


def load_novel(path: Path = NOVEL) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False)
    df["amount"] = pd.to_numeric(df.amount, errors="coerce").fillna(0.0)
    df["dir"] = df.direction.map({"Поступление": "in", "Списание": "out"})
    return df


def novel(clf: Classifier, repo: Path, path: Path = NOVEL) -> dict:
    df = load_novel(path)
    go = labels.go_rule_labels(path, repo, ML_DIR / "data" / "novel_rule_labels.csv")
    df["rule"] = df.id.map(dict(zip(go.id, go.category)))
    ops = [Op(d, p, n, i, a) for d, p, n, i, a in
           zip(df.dir, df.payment_purpose, df.counterparty_name, df.counterparty_inn, df.amount)]
    pr = clf.predict(ops)
    df["model"] = [p.category for p in pr]
    df["conf"] = [p.confidence for p in pr]
    df["chain"] = [r if r != OTHER else m for r, m in zip(df.rule, df.model)]
    df["hybrid"] = hybrid_predictions(df.rule, df.model, df.conf)
    res = {k: scores(df.category, df[k]) for k in ("rule", "model", "chain", "hybrid")}
    by_group = {}
    for g, s in df.groupby("group"):
        by_group[g] = dict(n=len(s), **{k: float((s.category == s[k]).mean()) for k in ("rule", "model", "chain", "hybrid")})
    unseen = df.payment_purpose.str.lower().str.contains("|".join(UNSEEN_CHANNELS), regex=True)
    by_group["(каналы вне словаря)"] = dict(n=int(unseen.sum()), **{
        k: float((df.category[unseen] == df[k][unseen]).mean()) for k in ("rule", "model", "chain", "hybrid")})
    res["confidence"] = confidence_metrics(df.category, df.model, df.conf)
    res["by_group"] = by_group
    res["df"] = df
    res["summary"] = dict(n=len(df), rules_acc=res["rule"]["accuracy"], model_acc=res["model"]["accuracy"],
                          chain_acc=res["chain"]["accuracy"], rules_f1=res["rule"]["macro_f1"],
                          model_f1=res["model"]["macro_f1"], chain_f1=res["chain"]["macro_f1"])
    # Порог «не уверен → other»: как меняется точность.
    thr = {}
    for t in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6):
        pred = [m if c >= t else OTHER for m, c in zip(_raw_top(clf, ops), [p.proba.max() for p in pr])]
        thr[t] = float((df.category == pd.Series(pred, index=df.index)).mean())
    res["threshold"] = thr
    return res


def _raw_top(clf: Classifier, ops: list[Op]) -> list[str]:
    return [CATEGORIES[j] for j in clf.predict_proba(ops).argmax(axis=1)]


def evaluate_all(clf: Classifier, ho_df, ho_rows, dev_rows, repo: Path) -> dict:
    res = dict(holdout=holdout(clf, ho_df, ho_rows), novel=novel(clf, repo))
    model, _ = predict_rows(clf, dev_rows)
    res["dev"] = scores([r["label"] for r in dev_rows], model)
    h, n = res["holdout"]["summary"], res["novel"]["summary"]
    print(f"  holdout: правила {h['rules_acc']:.3f} / модель {h['model_acc']:.3f} / цепочка {h['chain_acc']:.3f}")
    print(f"  novel:   правила {n['rules_acc']:.3f} / модель {n['model_acc']:.3f} / цепочка {n['chain_acc']:.3f}")
    print(f"  dev:     модель {res['dev']['accuracy']:.3f}")
    return res


# ------------------------------------------------------------------ отчёт

def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _md_table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _cell(s: str) -> str:
    return s.replace("|", "/").replace("\n", " ")


def write_report(results: dict, args, path: Path) -> None:
    h, nv = results["holdout"], results["novel"]
    fn = results.get("final_novel", nv)
    df = fn["df"]
    L = []
    L.append("# Классификатор категорий операций\n")
    L.append(f"Сгенерировано `python -m zavozik_ml.classify.train` {time.strftime('%Y-%m-%d')}. "
             "Код — `ml/zavozik_ml/classify/`, артефакт — `ml/artifacts/classifier/`, "
             "«новый» набор — `ml/zavozik_ml/classify/novel_test.csv`.\n")
    L.append(INTRO)
    L.append(f"Доля дополнительных примеров без контрагента: {getattr(args, 'name_dropout', .25):.0%}.\n")
    L.append("\nОценка разделена на обучение / калибровку / тест по компаниям (60/20/20). "
             "Метки пустых назначений по контрагентам строятся отдельно внутри каждой группы; "
             "данные test не меняют обучающие метки. Температура подбирается только на calibration-компаниях. Все компании синтетические и ранее "
             "исследовались; это внутренняя проверка. Набор novel уже просматривался при разработке "
             "и теперь считается регрессионным, а не независимым внешним тестом.\n")

    L.append("## 1. Отложенные компании датасета\n")
    L.append(f"{int(args.holdout * 100)}% компаний ({h['summary']['n']} операций) не участвуют в обучении. "
             "Эталон — метки «учителя» (правила Go + ручная доразметка шаблонов, которые правила "
             f"не покрыли); правила Go дали `other` на {h['n_rule_other']} из них.\n")
    rows = []
    for k, name in (("rules", "Правила Go"), ("model", "Модель"), ("chain", "Прежняя цепочка: правила → модель"), ("hybrid", "Go Hybrid, порог 0.8")):
        s = h[k]
        rows.append([name, _pct(s["accuracy"]), f"{s['macro_f1']:.3f}", _pct(s["turnover_accuracy"]),
                     _pct(s["other_turnover_share"])])
    L.append(_md_table(["", "Точность", "Macro-F1", "Точность по обороту", "Оборот в other"], rows))
    L.append(f"\nСогласие модели с правилами Go там, где правила уверены: **{_pct(h['agree_with_go_confident'])}**.\n")
    L.append("Главные ошибки модели (эталон → ответ, число операций): " +
             ", ".join(f"{t}→{p} ({n})" for (t, p), n in h["top_errors"][:8]) + ".\n")

    L.append("## 2. Регрессионный набор новых формулировок (не внешний тест)\n")
    L.append(f"{fn['summary']['n']} вручную составленных назначений; эталон и обоснование спорных — в CSV "
             "(колонки `category`, `note`). Финальная модель (обучена на всех компаниях); "
             f"модель из п. 1 (без отложенных компаний) даёт {_pct(nv['summary']['model_acc'])}.\n")
    rows = []
    for k, name in (("rule", "Правила Go"), ("model", "Модель"), ("chain", "Прежняя цепочка"), ("hybrid", "Go Hybrid, порог 0.8")):
        rows.append([name, _pct(fn[k]["accuracy"]), f"{fn[k]['macro_f1']:.3f}"])
    L.append(_md_table(["", "Точность", "Macro-F1"], rows))
    L.append("\nУверенность не гарантирует правильность. Статистика модели при пороге 0.8:\n")
    L.append(_md_table(["Набор", "ECE", "Доля уверенных", "Точность уверенных", "Уверенных ошибок"], [
        [name, f"{v['ece']:.4f}", _pct(v['accepted_fraction']), _pct(v['accepted_accuracy']), v['confident_errors']]
        for name, v in [("Company holdout", h['confidence']), ("Regression novel", fn['confidence'])]]))
    L.append("\nПо группам:\n")
    rows = [[g, v["n"], _pct(v["rule"]), _pct(v["model"]), _pct(v["chain"]), _pct(v["hybrid"])] for g, v in sorted(fn["by_group"].items())]
    L.append(_md_table(["Группа", "N", "Правила Go", "Модель", "Прежняя цепочка", "Hybrid"], rows))
    L.append("\nF1 модели по категориям (новый набор):\n")
    rows = [[c, f"{fn['model']['f1'].get(c, float('nan')):.2f}", f"{fn['rule']['f1'].get(c, float('nan')):.2f}",
             int((df.category == c).sum())] for c in CATEGORIES if (df.category == c).any()]
    L.append(_md_table(["Категория", "F1 модели", "F1 правил", "N"], rows))

    L.append("\nМатрица ошибок модели кратко (эталон → ответ, все ошибки):\n")
    err = Counter((t, m) for t, m in zip(df.category, df.model) if t != m)
    L.append(_md_table(["Эталон", "Ответ модели", "N"], [[t, m, n] for (t, m), n in err.most_common()]))

    if results.get("ablation"):
        L.append("\nАбляция (модели без отложенных компаний, новый набор): сколько даёт аугментация.\n")
        rows = [["Полная модель", _pct(nv["model"]["accuracy"]), f"{nv['model']['macro_f1']:.3f}",
                 _pct(nv["by_group"]["digital_ruble"]["model"]), _pct(nv["by_group"]["(каналы вне словаря)"]["model"])]]
        for name, a in results["ablation"].items():
            rows.append([name, _pct(a["model"]["accuracy"]), f"{a['model']['macro_f1']:.3f}",
                         _pct(a["by_group"]["digital_ruble"]["model"]), _pct(a["by_group"]["(каналы вне словаря)"]["model"])])
        L.append(_md_table(["Обучение", "Точность", "Macro-F1", "Цифровой рубль", "Каналы вне словаря"], rows))
    L.append("\nПорог «не уверен → other» (точность модели на новом наборе):\n")
    L.append(_md_table(["Порог", "Точность"], [[t, _pct(v)] for t, v in fn["threshold"].items()]))
    L.append(f"\nВ артефакте порог {args.min_confidence}.\n")

    L.append("## 3. Цифровой рубль\n")
    L.append(DIGITAL_RUBLE)
    dr = df[df.group == "digital_ruble"]
    L.append(f"\nТочность на {len(dr)} операциях с цифровым рублём: правила Go {_pct((dr.category == dr.rule).mean())}, "
             f"модель {_pct((dr.category == dr.model).mean())}, цепочка {_pct((dr.category == dr.chain).mean())}. "
             f"Ни одна не отнесена к несуществующей категории (выход модели — только из 20).\n")
    rows = [[r.direction[:4] + ".", _cell(r.payment_purpose[:90]), r.category, r.rule, r.model, f"{r.conf:.2f}"]
            for r in dr.itertuples()]
    L.append(_md_table(["Напр.", "Назначение", "Эталон", "Правила", "Модель", "Увер."], rows))

    L.append("\n## 4. Ошибки модели на новом наборе\n")
    bad = df[df.category != df.model]
    rows = [[r.id, r.group, _cell(r.payment_purpose[:70]) or "(пусто)", _cell(r.counterparty_name[:30]), r.category,
             r.model, f"{r.conf:.2f}"] for r in bad.itertuples()]
    L.append(_md_table(["id", "Группа", "Назначение", "Контрагент", "Эталон", "Модель", "Увер."], rows))

    d = results.get("dev")
    if d:
        L.append(f"\nDev (зашумлённые отложенные операции + синтетика, {d['n']} строк): точность модели "
                 f"{_pct(d['accuracy'])}, macro-F1 {d['macro_f1']:.3f}.\n")
    L.append(DECISIONS)
    L.append(LIMITS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


INTRO = """## Что это

Классификатор операции по экономическому смыслу в одну из 20 категорий
закрытого списка (`domain.AllCategories`). Новых категорий не бывает: выход —
softmax по 20 классам; если уверенность ниже порога, ответ `other`.

- **Вход:** назначение платежа, название контрагента, тип контрагента по длине ИНН
  (10 — организация, 12 — ИП/физлицо, пусто), направление, сумма (грубые полудекады).
  Сам ИНН в признаки не идёт.
- **Нормализация:** регистр, ё→е, латинские буквы-двойники в русских словах,
  даты/суммы/номера/месяцы → токены, хвосты про НДС убраны,
  **упоминание цифрового рубля вырезается** (это способ платежа, а не смысл).
- **Признаки:** хэшированные (2^18) слова, биграммы и символьные 3–5-граммы
  назначения и названия, каждый — ещё и в паре с направлением; мета-признаки
  (направление × тип контрагента, пустое назначение, сумма).
- **Модель:** мультиномиальная логистическая регрессия (L2, L-BFGS, scipy), веса
  калиброваны температурой. Инференс — только numpy, артефакт ~ несколько МБ.
- **Метки:** правила Go (тот же код, что в проде, — `backend/cmd/rulelabel`) +
  ручная доразметка всех шаблонов, где правила дают `other` (`labels.py`).
- **Аугментация** (`augment.py`): зашумлённые копии реальных назначений (опечатки,
  сокращения, регистр, латиница, обрезка реквизитов, новые каналы платежа, пустое
  назначение, обезличенный контрагент) и перефразировки по словарю смысла каждой
  категории, явный класс `other` (мусор, неинформативные фразы).
  Дополнительно часть примеров с непустым назначением получает копию без имени/ИНН:
  отсутствие контрагента не должно само по себе означать `other`. Та же процедура
  применяется к calibration; пустое назначение не теряет единственный источник смысла.
- **Интеграция:** доступны прежняя `Chain{Rules, ML}` и opt-in `Hybrid{Rules, ML}`.
  Hybrid позволяет модели с уверенностью ≥0.8 исправить правило, сохраняет ручные
  метки и использует правила при недоступном ML. Подключение в HTTP/import-потоке
  остаётся владельцу backend; gRPC-клиент и живая проверка поставляются здесь.

Эмбеддинги (мультиязычные sentence-модели) не пробовали: нужен torch и
сотни МБ артефакта, а линейная модель на символьных n-граммах уже держит
опечатки и перефразировки; это следующий шаг, если появится разметка чужих данных.
"""

DIGITAL_RUBLE = """Цифровой рубль — третья форма рубля, а не криптовалюта и не отдельная
категория. Категория определяется тем, **за что** и **кому** платят:

- оплата поставщику цифровыми рублями → `supplier`, зарплата на кошелёк ЦР → `salary`,
  налоги → `tax`, аренда → `rent` и т.д.;
- перевод с расчётного счёта на **собственный** счёт/кошелёк ЦР организации (и обратно)
  → `own_transfer` (как перевод между своими счетами в разных банках);
- перевод на личный кошелёк ЦР предпринимателя → `own_transfer` (как «перевод на
  личный счёт предпринимателя»); возврат займа учредителю на его кошелёк → `owner_loan`;
- розничные оплаты покупателей цифровыми рублями по QR → `revenue_sbp` (тот же
  смысл, что у оплат по QR через СБП: мгновенная оплата физлица в магазине);
  оплата организацией по счёту в ЦР → `revenue_b2b`; эквайринг остаётся эквайрингом.

Как это сделано: нормализация вырезает «цифровыми рублями», «кошелёк цифрового рубля»,
«цифровая форма рубля», «ЦР» и т.п. до признаков, это уменьшает влияние формы рубля на признаки;
оставшийся контекст счёта/кошелька всё ещё может влиять на результат. Правила Go про ЦР ничего не знают и угадывают, только
если остальной текст совпал с их регулярками.
"""

DECISIONS = """
## Решения по спорным случаям

- **Займ/кредит на приход.** Выдача банковского кредита (приход) → `loan_payment`:
  в закрытом списке это единственная «кредитная» категория; направление показывает, что
  это поступление. Деньги учредителя в бизнес (займ, взнос в уставный капитал,
  пополнение для закрытия овердрафта) → `owner_loan`.
- **Вывод денег владельцем.** Дивиденды участнику и «перевод на личный счёт/карту
  предпринимателя» → `own_transfer` (так правила Go уже размечают «Перевод собственных
  средств ИП на счёт физического лица»). Это деньги владельца, а не расход бизнеса.
- **Закупки, не названные «товаром».** «Оплата по счёту за кровельные материалы /
  оборудование / автомобиль», топливные карты → `supplier`; подписка на ПО, субподряд,
  ремонт, обслуживание, Платон, лабораторные исследования → `services`. Правила Go
  отдавали всё это в `other` (≈ 10% оборота датасета).
- **Агентские выплаты площадок** (бронирование, доставка, маркетплейсы) → `revenue_marketplace`.
- **Субсидии, гранты, страховое возмещение** → `other`: смысл ясен, но подходящей
  категории в закрытом списке нет (это не выручка, не займ и не возврат).
- **Пустое назначение** без «говорящего» контрагента (банк, физлицо) → `other`.
- **Исправление правил:** «Перечисление остатка … в связи с закрытием счёта» правила Go
  относят к `utilities` (совпадение «связи»); в метках учителя — `own_transfer`.
  Сами правила Go не меняли — это задача владельца `categorize`.
- **B2B-оплата через СБП** (организация платит по счёту через СБП/B2B-QR) → `revenue_b2b`,
  а не `revenue_sbp`: `revenue_sbp` — розничная выручка по QR.
"""

LIMITS = """
## Ограничения и честность оценки

- Эталон на датасете — слабые метки (правила + ручная разметка шаблонов), не золотая
  разметка операций. Данные синтетические: 2200 шаблонов назначений, поэтому точность на
  отложенных компаниях высокая у всех и мало что говорит о чужих данных.
- «Новый» набор и словари аугментации писал один автор. Набор составлен до словарей и в
  обучение не идёт, но стиль формулировок мог совпасть — реальная точность на чужих
  выписках, скорее всего, ниже. Часть каналов из набора нарочно не попала в словари:
  «Долями», ЮKassa, оплата по биометрии, T-Pay, платёжный стикер, cash-in, Диадок,
  «Мой налог», смарт-контракт. После просмотра ошибок это регрессионные примеры,
  а не доказательство независимого обобщения.
- Температура подобрана на отдельной calibration-группе (шум + синтетика).
  Пороги 0.3 (abstention) и 0.8 (Hybrid) — фиксированные настройки; их нельзя считать
  оптимальными для внешних выписок без независимой разметки.
- Модель не видит историю контрагента и компании — это может дать отдельный шаг
  (например, категория, которую пользователь уже поставил этому контрагенту).
"""


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--test", type=Path, default=NOVEL)
    a = ap.parse_args()
    res = novel(Classifier.load(a.artifact), ML_DIR.parent, a.test)
    s = res["summary"]
    print(f"N={s['n']}: правила {s['rules_acc']:.3f}, модель {s['model_acc']:.3f}, цепочка {s['chain_acc']:.3f}")
    for g, v in sorted(res["by_group"].items()):
        print(f"  {g:14s} n={v['n']:3d} правила {v['rule']:.2f} модель {v['model']:.2f} цепочка {v['chain']:.2f}")


if __name__ == "__main__":
    main()

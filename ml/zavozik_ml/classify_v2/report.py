"""Render reproducible acceptance results without selecting/tuning a model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def acceptance(evaluation: dict, benchmark: dict, novelty: dict | None) -> dict:
    d = evaluation["datasets"]
    company, regression, authored = d["company_test"], d["novel_regression"], d["authored_holdout"]
    digital = [x.get("digital_ruble") for x in (regression, authored)]
    gates = {
        "company_accuracy_within_0_3pp": company["category"]["accuracy"] >= company["linear_v1"]["accuracy"] - .003,
        "company_macro_f1_within_0_3pp": company["category"]["macro_f1"] >= company["linear_v1"]["macro_f1"] - .003,
        "regression_accuracy_at_least_97_9_percent": regression["category"]["accuracy"] >= .979,
        "new_holdout_category_better_than_v1": authored["category"]["accuracy"] > authored["linear_v1"]["accuracy"],
        "digital_ruble_all_category_and_channel_correct": all(
            x is not None and x["n"] > 0 and x["category_correct"] == x["n"]
            and x["channel_correct"] == x["n"] and x["categories_in_taxonomy"] for x in digital),
        "new_holdout_channel_accuracy_at_least_95_percent": authored["channel"]["accuracy"] >= .95,
        "new_holdout_tags_micro_f1_at_least_0_9": authored["tags"]["micro_f1"] >= .9,
        "category_ece_at_most_0_05": company["category"]["ece"] <= .05,
        "complete_cpu_batch_256_p95_at_most_1s": benchmark["batch_size"] == 256 and benchmark["distinct_normalized_inputs"] == 256 and benchmark["p95_s"] <= 1,
        "hidden_category_novelty_recall_at_least_80_percent": bool(novelty and novelty["hidden_novel_recall"] is not None and novelty["hidden_novel_recall"] >= .8),
        "known_category_novelty_fpr_at_most_5_percent": bool(novelty and novelty["known_false_positive_rate"] <= .05),
    }
    return {"all_passed": all(gates.values()), "gates": gates,
            "novelty_evaluated": novelty is not None,
            "policy": "Report only; no automatic activation or replacement of v1",
            "regression_rounding": "literal >=.979 requires at least275/280; v1 is274/280, rounded97.9%"}


def render(evaluation: dict, benchmark: dict, novelty: dict | None, selection: dict | None = None) -> str:
    status = acceptance(evaluation, benchmark, novelty)
    provenance = evaluation["provenance"]
    lines = ["# Классификатор операций v2", "",
             f"Артефакт `{provenance['model_version']}`, taxonomy `{provenance['taxonomy_version']}`.", "",
             "Модель выдаёт фиксированный нормированный embedding, одну категорию и её полное распределение, "
             "один канал и распределение каналов, независимые теги, атрибуты из справочника и novelty score.", "",
             "## Протокол", "",
             "90 компаний для обучения,30 для калибровки,30 для company test — те же списки, что у linear-v1. "
             "Для company-сравнения использован сохранённый evaluation-only v1; выпущенный v1 обучался на всех компаниях "
             "и используется только для authored/regression-сравнения. Статистические weak labels изолированы по partitions.", "",
             "Категории датасета размечены правилами Go и ручными правилами шаблонов, каналы/теги — regex weak labels. "
             "Это не независимая человеческая оценка на настоящих выписках. Новый авторский синтетический набор182 "
             "заморожен до обучения; novel280 ранее изучался и является regression-проверкой. "
             "После просмотра итоговых ошибок модель, пороги и примеры не подбирались заново.", "",
             "## Сравнение категорий", "",
             "| Проверка | N | linear-v1 accuracy | encoder accuracy | encoder macro-F1 | encoder ECE |",
             "|---|---:|---:|---:|---:|---:|"]
    names = {"company_test": "Отложенные компании, weak labels", "novel_regression": "Старый regression-набор",
             "authored_holdout": "Новый замороженный авторский набор"}
    for key, data in evaluation["datasets"].items():
        c, base = data["category"], data["linear_v1"]
        lines.append(f"| {names[key]} | {c['n']} | {base['accuracy']:.6%} | {c['accuracy']:.6%} | {c['macro_f1']:.6f} | {c['ece']:.6f} |")
    lines += ["", "Порог97.9% проверяется буквально: не менее275/280. Точное значение v1 —274/280=97.8571429%.",
              "", "## Каналы, теги и цифровой рубль", "",
              "| Проверка | Accuracy канала | Micro-F1 тегов | Источник меток |",
              "|---|---:|---:|---|"]
    for key in ("company_test", "authored_holdout"):
        data = evaluation["datasets"][key]
        lines.append(f"| {names[key]} | {data['channel']['accuracy']:.6%} | {data['tags']['micro_f1']:.6f} | {'weak regex' if key == 'company_test' else 'авторские, зафиксированы до fit'} |")
    lines += ["", "У старого novel-набора нет независимых channel/tag gold; метки разметчика не выдавались за gold.", ""]
    for key in ("novel_regression", "authored_holdout"):
        if digital := evaluation["datasets"][key].get("digital_ruble"):
            lines.append(f"- {names[key]}, цифровой рубль: категория {digital['category_correct']}/{digital['n']}, "
                         f"канал digital_ruble {digital['channel_correct']}/{digital['n']}.")
    lines += ["", "Цифровой рубль — канал; автоматическое добавление категорий и категория «крипта» отсутствуют. "
              "Атрибуты — свойства выбранной категории, не отдельный прогноз. Типовое direction справочника "
              "не заменяет фактическое направление операции (например, получение кредита в legacy loan_payment).", "",
              "## Новизна и расширение", ""]
    if novelty is None:
        lines.append("Эксперимент скрытых категорий ещё не выполнен; критерии новизны не объявляются пройденными.")
    else:
        lines += [f"Скрыты `{', '.join(novelty['hidden_categories'])}` из всех fitting/calibration targets. "
                  "Порог определяется только известными calibration-операциями. Кластеры/центры строятся на скрытых "
                  "операциях calibration-компаний; качество после добавления проверяется на отдельных test-компаниях.", "",
                  f"Найдено novel: **{novelty['hidden_novel_recall']:.4%}**, ложных novel на известных: "
                  f"**{novelty['known_false_positive_rate']:.4%}**. "
                  f"Точность скрытых после расширения: **{novelty['after_extension_hidden_accuracy']:.4%}**.", "",
                  "| Скрытая категория | N test | Найдено novel | Recall | Accuracy после добавления |",
                  "|---|---:|---:|---:|---:|"]
        for name, s in novelty["per_hidden_category"].items():
            lines.append(f"| {name} | {s['n']} | {s['novel_detected']} | {s['novel_recall']:.4%} | {s['accuracy_after_extension']:.4%} |")
        lines += ["", f"Известные категории: accuracy до {novelty['known_accuracy_before']:.4%}, после {novelty['known_accuracy_after']:.4%}. "
                  f"Discovery: {novelty['discovery_rows']} строк, {novelty['discovery_unique_texts']} уникальных входов.", "",
                  "Название кластера подтверждалось **симуляцией oracle** по discovery-меткам; это не реальное "
                  "человеческое подтверждение. Тестовые точки не использовались для собственных прототипов. "
                  "Мало enforcement-событий и синтетические шаблоны ограничивают переносимость результата."]
    lines += ["", "Production сам не создаёт категории. CLI discovery даёт кандидатов/синонимы; approve требует "
              "reviewer и подтверждённый документ категории, создаёт новый taxonomy_version и новый артефакт. "
              "Энкодер остаётся неизменным; перед активацией расширения нужна новая проверка известных классов.", "",
              "## CPU и сервис", "",
              f"Полный batch256: median **{benchmark['median_s']:.4f}с**, p95 **{benchmark['p95_s']:.4f}с**, "
              f"max **{benchmark['max_s']:.4f}с**; {benchmark['repeats']} повторений после прогрева. "
              "Все256 нормализованных входов различны; измерены нормализация, токенизация, CPU encoder, "
              "головы, словари вероятностей и атрибуты. Startup/сеть исключены. Это локальное измерение, не SLA сервера.", "",
              "v2 зарегистрирован рядом с v1 и включается явно через ML_CLASSIFIER_V2. Для PyTorch "
              "используется отдельный локальный worker, исключающий конфликт OpenMP с LightGBM; проверены "
              "сосуществование с v1/GBM и восстановление worker после завершения. Go не подключался.", "",
              "## Приёмка", "", "| Критерий | Результат |", "|---|---|"]
    for gate, passed in status["gates"].items():
        lines.append(f"| `{gate}` | {'PASS' if passed else 'FAIL / NOT RUN'} |")
    lines += ["", "**Все критерии пройдены.**" if status["all_passed"] else
              "**Есть непройденные критерии. Модель сохраняет статус исследовательского кандидата; v1 автоматически не заменялся.**", "",
              "## Воспроизведение и ограничения", "",
              "Команды: `ml/zavozik_ml/classify_v2/README.md`. SHA файлов/базы, train/cal/test split, "
              "нормализация и параметры находятся в config/manifest модели. Сравнение runtime и его "
              "калибровка сохранены отдельно. Никакие операции не отправлялись во внешние inference API.", "",
              "Нужна независимая разметка реальных новых компаний, особенно редких категорий, "
              "неоднозначных назначений, новых каналов и open-set примеров. Высокая confidence не заменяет "
              "первичные документы. Embedding разных model_version нельзя смешивать; расширение справочника "
              "требует учёта taxonomy_version. Финальные наборы после этого прогона считаются просмотренными.", ""]
    if selection:
        lines += ["## Выбор по calibration", "", "```json", json.dumps(selection, ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evaluation", type=Path, required=True)
    p.add_argument("--benchmark", type=Path, required=True)
    p.add_argument("--novelty", type=Path)
    p.add_argument("--selection", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--acceptance-out", type=Path, required=True)
    args = p.parse_args()
    ev, bench = json.loads(args.evaluation.read_text()), json.loads(args.benchmark.read_text())
    nov = json.loads(args.novelty.read_text()) if args.novelty else None
    selection = json.loads(args.selection.read_text()) if args.selection else None
    args.out.write_text(render(ev, bench, nov, selection))
    args.acceptance_out.write_text(json.dumps(acceptance(ev, bench, nov), indent=2) + "\n")


if __name__ == "__main__":
    main()

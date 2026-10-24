# Дополнительные проверки ML

Эти скрипты не регистрируют новые модели в production-сервисе. Результаты
экспериментов нельзя автоматически считать независимой проверкой: текущий
синтетический датасет уже изучался при разработке.

Из корня репозитория, с подготовленной `ml/data/flows.csv`:

```bash
PYTHONPATH=ml/gen ml/.venv/bin/python ml/experiments/excluded_cohort.py
PYTHONPATH=ml/gen ml/.venv/bin/python ml/experiments/audit_uncertainty.py
PYTHONPATH=ml/gen ml/.venv/bin/python ml/experiments/service_stress.py --address 127.0.0.1:50051
PYTHONPATH=ml/gen ml/.venv/bin/python ml/experiments/classifier_partition_labels.py
```

- `excluded_cohort.py`: 13 компаний вне основного временного окна; исключает их
  и 30 audit-компаний из каждого fit. Требует `reports/metrics/company_coverage.csv`.
- `audit_uncertainty.py`: парный bootstrap по компаниям для готового
  `data/final_audit.parquet`. Не переобучает модель и не выбирает параметры.
- `service_stress.py`: конкурентные реальные gRPC-запросы, детерминизм,
  ограничения батчей и восстановление после отмены. Запускать на явно выбранном
  тестовом сервере, чтобы не нагружать рабочую среду коллег.
- `classifier_partition_labels.py`: повтор внутреннего company holdout с
  построением слабых меток только внутри соответствующей группы компаний.
  Требует сохранённый split `data/classifier_evaluation/meta.json`.

## Chronos: отдельное окружение

[Chronos-T5](https://github.com/amazon-science/chronos-forecasting) генерирует
целые траектории, что позволяет считать накопленный остаток. Здесь модель
предсказывает **чистый поток**. Его положительные/отрицательные части не являются
прогнозом валовых поступлений/списаний. Эксперимент не подменяет serving-модель.

```bash
python3.12 -m venv ml/data/chronos_venv
ml/data/chronos_venv/bin/pip install -r ml/experiments/requirements-chronos.lock
ml/data/chronos_venv/bin/pip install --no-deps -e ml
export HF_HOME="$PWD/ml/data/hf_cache"
export HF_HUB_DISABLE_TELEMETRY=1
ml/data/chronos_venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('amazon/chronos-t5-tiny',
    revision='29d808298f1a62493e7b9a5e08529d0d930fa189',
    allow_patterns=['config.json','generation_config.json','model.safetensors','README.md'])
PY
HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 PYTHONPATH=ml/gen \
  ml/data/chronos_venv/bin/python ml/experiments/chronos_shadow.py --paths 600
```

Нужны уже рассчитанные development origins `data/final_development.parquet`;
скрипт проверяет отсутствие audit-компаний и дат после границы development.
Промежуточный parquet сохраняется каждые 10 origins. Метаданные фиксируют
revision и SHA256 весов, входа и скрипта. Данные остаются на локальной машине;
в сеть скачиваются только публичные веса. Лицензия модели Apache 2.0.
CPU-инференс проверялся с 4 потоками; большие батчи требуют заметной памяти.

Более крупный вариант того же семейства: `chronos_small_shadow.py`,
[Chronos-T5 Small](https://huggingface.co/amazon/chronos-t5-small), revision
`a971ba21945c4f1796b17a91fe69214b5f4ad472`. Скачивается тем же способом, только
с указанными model/revision; затем запускается offline тем же интерпретатором.
По умолчанию 200 путей и только standard-сценарий. Не запускать одновременно
с Tiny на машине с ограниченной памятью. Это сравнительный эксперимент,
а не автоматическое переключение модели.

`risk_thresholds.py` описывает компромисс числа сигналов и пропусков только на
сохранённом development-прогоне. Порог Go 0.1 не меняется. Таблица не доказывает,
что какой-то другой порог оптимален без стоимости ложного сигнала и пропуска.

`classifier_robustness.py` проверяет регистр, пробелы, нейтральные суффиксы,
масштаб суммы и отсутствие контрагента на старом regression-наборе.
`classifier_counterparty_dropout.py` проверяет фиксированный вариант обучения
с 25% дополнительных примеров без имени/ИНН при непустом назначении. Пустое
назначение не сохраняет метку после удаления единственного источника смысла.

`service_limits.py --address 127.0.0.1:50051` проверяет 5000 различных
операций суммарным текстом около 1.6 млн символов и допустимый прогноз на
1 млн ячеек путей. Это разовая проверка границ, не измерение production SLA.
`purged_development.py` пересчитывает метрики сохранённых прогнозов только там,
где весь будущий факт строго предшествует границе audit; модели не переобучаются.
`classifier_finalize.py` обучает окончательный candidate на всех компаниях по
фиксированному рецепту dropout, используя уже сохранённую независимую calibration
температуры. Скрипт пишет в data/, а не автоматически заменяет production artifact.

`chronos_report.py` объединяет только законченные shadow-прогоны; неполные
checkpoint не выдаются за результат по всему набору. `chronos_calibration.py`
проверяет bootstrap полных нормированных траекторий ошибок Chronos по другим
группам компаний и только тем горизонтам, которые уже закончились до текущей
даты прогноза. Нужны минимум 20 calibration-компаний. Результат остаётся
исследовательским net-flow прогнозом и не меняет gRPC/auto.

## Независимая ручная проверка категорий

```bash
ml/.venv/bin/python ml/experiments/prepare_category_review.py --out ml/data/category_review_v1
```

Создаёт две одинаковые пустые JSONL-формы для независимых проверяющих: 200 случайных
операций и 50 дополнительных операций с пустым назначением, без повторов.
Модельные/слабые метки в формы не попадают; соответствие когорт хранится отдельно
в manifest. Существующую папку инструмент не перезаписывает. Нужны человеческие
ответы и разбор разногласий; скрипт не генерирует правильные категории.
Инструкция различает `unresolved` (не хватает контекста) и установленную категорию
`other`. Для неопределимых платежей понадобятся договоры/первичные документы.

Случайную и усложнённую когорты нельзя смешивать в общую оценку accuracy.
Данные кейса уже были изучены и использованы при обучении: новая ручная разметка
улучшит качество меток, но не сделает эти операции независимым тестовым набором.
Для внешнего теста передайте `--data` с новым набором той же схемы.

После заполнения форм:

```bash
ml/.venv/bin/python ml/experiments/validate_category_review.py \
  --manifest ml/data/category_review_v1/selection_manifest.json \
  --reviewer-a ml/data/category_review_v1/reviewer_a.jsonl \
  --reviewer-b ml/data/category_review_v1/reviewer_b.jsonl \
  --out ml/data/category_review_validation_v1
```

Валидатор сверяет хеш исходного датасета, исходные поля каждой операции,
уникальность и полный охват ID, допустимость категории/статуса и наличие
проверяющего/обоснования. Совпадающие имена двух проверяющих отклоняются;
реальную независимость людей программа проверить не может. Пустые формы дают
ноль согласованных меток. Разногласия, недостаток данных и незаполненные строки
отделены от `consensus_candidates`; автоматического продвижения в gold нет.
Отчёт показывает согласие и незавершённость отдельно по каждой когорте,
не выдаёт согласие людей за accuracy модели. Для внешнего набора также укажите
`--data`, соответствующий manifest.

## Проверка Chronos на действительно коротких историях

`chronos_supplemental.py` проверяет фиксированный Tiny на 54 сохранённых
supplemental origins. Дополнительно пробует прежний рецепт калибровки только
там, где доступны ≥20 других development-компаний с полностью завершённым
целевым горизонтом до текущей даты и строго до 2026-07-01. Для историй ≤14/28
дней используются соответствующие stress-остатки, иначе standard. Выбор
зафиксирован до расчёта результата; serving не меняется. Модели сравниваются
на одинаковых подмножествах. Ранние 2025-прогнозы не получают ошибки из 2026 года.

Запускать как `chronos_shadow.py` в отдельном offline-окружении. На macOS
сначала импортируется Torch, затем backtest/LightGBM, как в исходном рабочем
runner: обратный порядок в этом окружении приводил к native segmentation fault.
Программа загружает те же pinned Tiny-веса, не запускает новый fit и не читает
frozen audit predictions. Результаты: `reports/chronos_supplemental.md`.

# Классификатор v2

Одна операция даёт нормированный embedding, одну категорию, распределение
категорий, один канал, независимые теги, атрибуты категории и novelty score.
Векторы сопоставимы только внутри одной версии энкодера. Порядок/количество
категорий определяется taxonomy артефакта, а не клиентским enum.

## Данные и обучение

Штатное `ml/.venv` не требует torch. Создайте отдельное окружение и установите
`pip install -e 'ml[train,dev]'`; на macOS обучение использует MPS, иначе CPU
или явно указанный `--device cuda`. Команды из корня репозитория:

```sh
export PYTHONPATH=ml/gen:ml
python -m zavozik_ml.classify_v2.fetch_base \
  --model cointegrated/rubert-tiny2 --out ml/data/classifier_v2/base/rubert-tiny2
python -m zavozik_ml.classify_v2.data --out ml/data/classifier_v2/prepared
python -m zavozik_ml.classify_v2.token_audit \
  --prepared ml/data/classifier_v2/prepared \
  --base ml/data/classifier_v2/base/rubert-tiny2/REVISION --prefix '' \
  --base ml/data/classifier_v2/base/e5-small/REVISION --prefix 'query: '
python -m zavozik_ml.classify_v2.train \
  --base ml/data/classifier_v2/base/rubert-tiny2/REVISION \
  --prepared ml/data/classifier_v2/prepared --out ml/data/classifier_v2/run
python -m zavozik_ml.classify_v2.export \
  --selected ml/data/classifier_v2/run/selected \
  --prepared ml/data/classifier_v2/prepared --out ml/data/classifier_v2/candidate
```

Загрузчик скачивает только публичные pretrained-файлы, фиксирует revision и
SHA-256, требует safetensors; загрузка модели всегда offline, без remote code.
Данные операций остаются локально. Для E5 используются `--pooling mean` и
`--text-prefix 'query: '`. Сначала выбирается энкодер по calibration-компаниям,
затем формат runtime по качеству и скорости на тех же calibration-компаниях.

Начальное разбиение90/30/30 компаний совпадает с v1. Семейства шаблонов
строятся ДО аугментации: номера/даты/документы/периоды/суммы и известные
слоты товаров/услуг/банков/регионов маскируются, близкие строки объединяются
транзитивно (SequenceMatcher≥.90,3gram Jaccard≥.65). Для опечаток сохраняются
и немаскированные aliases. Семейство назначается одному partition, остальные
его вхождения удаляются. Простое объединение компаний по общим шаблонам
связало бы почти весь датасет в одну компоненту. Потери/coverage раскрываются
в template_purging/data_manifest, исходные операции не переносятся между компаниями.

Teacher категории — Go rules и ручные правила v1; каналы/теги — weak labels.
Статистические метки пустого назначения пересчитываются ПОСЛЕ purging внутри
retained partition. Primary calibration/test содержат только реальные записи,
никаких4000 perturbations. Аугментация train наследует parent_id/company/family;
синтетика/искажения, совпавшие с heldout family, исключаются. split_audit
проверяет lineage, компании, normalised inputs, raw/slot-masked/near templates.
token_audit дополнительно исключает совпадения реальных128-token входов обоих
энкодеров. Train отказывается работать без прошедших проверок и совпадающих SHA.

Для честного сравнения refit baseline: `python -m zavozik_ml.classify_v2.baseline
--prepared ... --out ...`. Он использует ТОЧНО подготовленный train и clean
calibration, без повторного вызова старой аугментации. Старые company accuracy
и старый evaluation-only v1 к этому протоколу неприменимы. Отчёт показывает
также macro accuracy по test-семействам и неподдержанные категории; высокая
accuracy на weak labels не означает независимое качество на реальных выписках.

Подготовленные файлы и исходники проверяются по хэшам. После изменения
разметчика/нормализации надо создать новый prepared-каталог. Скрипт обучения
читает только train/calibration, не company test и не authored holdout.
Скрипт export сравнивает Torch/ONNX float32/int8, калибрует выбранный runtime
заново и сохраняет реальные результаты измерения. Наличие ONNX не означает,
что он автоматически выбран. PyTorch допустим, если он лучше по качеству.

На MPS обучение использует фиксированную длину padding, ограничивает allocator
через LOW_WATERMARK=.7/HIGH_WATERMARK=1.0 и освобождает свободный кэш каждые100
батчей. Это ограничивает рост памяти при множестве форм графа; attention mask,
loss и оптимизатор сохраняются. Параметры записываются в training_runtime.
Checkpoint/release содержит fit_source с исходниками, соответствующими
training_files_sha256; runtime никогда не импортирует этот архив. Для старого
checkpoint после изменения кода экспортируйте с `--fit-source /path/to/frozen-ml-root`.

Novelty — calibration rank расстояния до ближайшего прототипа. Для
предсказанной категории с≥30 calibration-наблюдениями используется её
собственная шкала; для редких и новых категорий — общая. Порог.95 фиксирован
по известным calibration-операциям. Это степень геометрической необычности,
а не вероятность существования новой категории и не гарантия5% FPR вне
этой выборки. После расширения справочника нужна отдельная проверка.

## Итоговая оценка

`heldout_v1.tsv` (182 авторских синтетических примера) и его SHA зафиксированы
до обучения. Это не независимый human gold. Не использовать набор для выбора
параметров, не менять примеры после просмотра результатов. Старый
`classify/novel_test.csv` — уже изученная regression-проверка.

```sh
python -m zavozik_ml.classify_v2.evaluate \
  --model ml/data/classifier_v2/candidate \
  --prepared ml/data/classifier_v2/prepared \
  --baseline-company ml/data/classifier_counterparty_dropout \
  --overlap-report ml/data/classifier_v2/fixture_overlap.json \
  --out ml/data/classifier_v2/final_evaluation --unlock-heldout
```

Для company test нужен сохранённый **evaluation-only** v1 с теми же90 train и
30 test-компаниями; финальный v1 обучался на всех компаниях и не подходит для
такого сравнения. На authored/regression сравнение делается с выпущенным v1.
Финальные результаты нельзя молча перезаписывать/подменять новым подбором.
До просмотра предсказаний можно выполнить `python -m
zavozik_ml.classify_v2.audit_inputs --train .../train.jsonl --out
ml/data/classifier_v2/fixture_overlap.json`: пустые/мусорные строки могут
совпадать с обучением по построению. В отчёте отдельно показывается поднабор
без полного совпадения нормализованного входа; исходный frozen-файл не меняется.

## Запуск сервиса

`proto/categorize/v2/categorizer.proto` — новый контракт, v1 не менялся.
Вход передаёт тип контрагента, а не ИНН. Атрибуты описывают типовую категорию,
поэтому фактическое направление входящей операции передаётся отдельно.
Пример: действующий справочник относит получение банковского кредита к
`loan_payment`, чьё типовое `direction` равно `out`.

```sh
pip install -e 'ml[encoder]'        # ONNX runtime
# либо: pip install -e 'ml[encoder-torch]'
ML_CLASSIFIER_V2=/absolute/path/to/encoder-v1-HASH \
PYTHONPATH=ml/gen:ml python -m zavozik_ml.serving.server
```

По умолчанию используется runtime из артефакта. `ML_CLASSIFIER_V2_BACKEND=torch`
явно выбирает PyTorch. Без `ML_CLASSIFIER_V2` v2 отвечает FAILED_PRECONDITION,
v1 и прогноз работают как раньше. Ошибочно настроенный путь/хэш прекращает
startup — подмена модели не допускается. Лимиты:1024операции,1млн символов,
8192символа назначения,1024названия,256ID; amount конечный,0..1e15.
PyTorch-инференс сервера автоматически изолирован в отдельном локальном
worker, чтобы его OpenMP не конфликтовал с LightGBM. Worker не хранит
операции и не вызывает внешние API; таймаут/отказ даёт UNAVAILABLE,
следующий запрос может восстановить worker. Его остановка включена в shutdown.

Для Docker: `docker build -f ml/Dockerfile --build-arg ML_EXTRA=encoder ml`;
для PyTorch — `ML_EXTRA=encoder-torch` (CPU wheel). Каталог модели монтируется
read-only, например `/models/current`, переменная ML_CLASSIFIER_V2 указывает
внутрь контейнера. Веса не встраиваются в Git/Docker context автоматически.
Go-клиент v2 и его подключение остаются задачей владельца backend.

## Новые категории

Сервис не хранит пользовательские операции. Backend может локально сохранять
ответы `is_novel` вместе с ID/назначением для офлайн-проверки. Не смешивать
эмбеддинги разных model_version; taxonomy_version также обязана совпадать.

```sh
python -m zavozik_ml.classify_v2.discovery propose \
  --model /path/to/model --predictions /path/to/predictions.jsonl \
  --out ml/data/category_candidates
```

HDBSCAN выдаёт размер, представителей, центр, ближайшую категорию и предложения
названия/атрибутов. Почти совпадающий кластер помечается synonym_review;
категория из него автоматически не создаётся. Название и атрибуты — только
подсказки. Для явного подтверждения:

```sh
python -m zavozik_ml.classify_v2.discovery approve \
  --model /path/to/model \
  --report ml/data/category_candidates/candidates.json \
  --centers ml/data/category_candidates/centers.npz \
  --candidate cluster_000 --reviewed-category /path/to/reviewed_category.json \
  --taxonomy-version ru-operations-v2.N --reviewer reviewer-name \
  --model-root ml/models/classifiers --workdir ml/data/reviewed_extension
```

`reviewed_category.json` содержит key/title_ru/description_ru/attributes,
как в taxonomy.json. Создаётся новый артефакт, старый не меняется. Энкодер
не переобучается. Перед активацией нужны повторная калибровка и проверка
ошибочных переключений известных категорий.

Проверка механизма: обучить отдельный run с `--hide leasing,enforcement`,
экспортировать, затем `python -m zavozik_ml.classify_v2.novelty_experiment`.
Discovery использует все операции calibration-компаний, включая ложные novel
из известных категорий; предварительной фильтрации по скрытым gold-классам нет.
Оценка использует test-компании. Название
скрытого класса подтверждается симуляцией oracle по меткам discovery,
что отдельно раскрывается в отчёте и не выдаётся за человеческое согласование.

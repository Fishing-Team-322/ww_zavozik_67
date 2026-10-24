# Классификатор v2: журнал реализации

## 2026-10-24 — начало

- Задача: `docs/CLASSIFIER_V2_SPEC.md`, ветка `ml`, исходный commit `d336b39`.
  Выполнен `git fetch origin`; `origin/ml` совпадает с текущей веткой.
- Сохранить v1 и forecast без изменений. Реализовать отдельные taxonomy,
  многовыходной encoder, подготовку/обучение/оценку, discovery и gRPC v2.
  Go-подключение не входит в задачу. Большие веса — только локально.
- Разделение компаний берётся из `ml/artifacts/classifier/meta.json`.
  Статистические weak labels строятся отдельно внутри каждого partition.
- До обучения фиксируется новый авторский синтетический набор >=150 операций
  с независимыми вручную заданными category/channel/tags. Не является внешним
  human gold. После заморозки не редактируется и не используется для выбора
  модели, аугментаций, порогов или параметров.
- Точное исходное значение novel accuracy v1 — 274/280 = 97.8571429%; в ТЗ
  округлено до97.9%. Приёмка и сравнение должны показывать точные значения.
- Обучение/экспорт — в отдельном окружении `ml/data/chronos_venv`; штатное
  `ml/.venv` не менять. CPU serving планируется через ONNX + tokenizers,
  с optional-зависимостями. Никакие данные не отправлять внешним API.
- Пользователь отошёл и просит вопросы отложить до возвращения. Работа
  продолжается автономно; возможные вопросы сохраняются в журнале.

## Подготовка до обучения

- Новый набор заморожен коммитом1e86a04:182операции,20категорий,8каналов,
  38digital-ruble случаев. SHA256 b457c8d7453bee48a3683853f6aeb37b72da3ce6f478e487e18c1f1dc5c73d23.
  Пустые TSV-поля намеренные; .gitattributes разрешает завершающий разделитель.
- Разметчик каналов/тегов, нормализация с сохранением цифрового рубля и
  taxonomy-проверки:25тестов прошли. Исправлено совпадение «доплата» внутри
  «предоплата», обнаруженное обычным unit-тестом, не отложенным набором.
- Company splits идентичныv1:90train/30calibration/30test. Получено59416train
  строк после дедупликации/аугментации,5258calibration views и50148test операций.
  Статистические teacher labels изолированы внутри каждого раздела.
- В train-окружение добавлены ONNX/ORT/sklearn; ml/.venv не менялось.
  HF Python-клиент дал TLS EOF, curl с включённой проверкой сертификата работает.
  Загружен safetensors rubert-tiny2@e8ed3b0c8bbf4fb6984c3de043bf7d2f4e5969ae.
  E5-small загружается для сравнения на calibration; данные никуда не отправляются.
- Уточнение пользователя: PyTorch на сервере допустим, качество важнее веса
  runtime. ONNX выбирается только после проверки качества/паритета.

## Реализация и обновление weak labels

- Реализованы многовыходной prototype encoder, Torch/MPS training с supervised
  contrastive loss, calibration, CPU backend Torch/ONNX, проверка хэшей артефакта,
  отдельный proto/gRPC v2. v1 остаётся зарегистрированным; v2 включается только
  через ML_CLASSIFIER_V2. Go не подключался.
- Первый полный run1 остановлен SIGTERM на PID25662 после найденной unit-тестом
  ошибки auxiliary teacher: «Без налога (НДС)» ошибочно давало budget_payment.
  Дополнительно уточнены owner-money/refund признаки для закрытия собственного
  счета. Исправленный teacher имеет версиюv2.2. Старые результаты оставлены
  в ignored data для диагностики, в итоговое сравнение не идут.
- Подготовлен отдельный prepared_v2 с provenance всех файлов разметки и
  нормализации. train проверяет source SHA и хэши train/calibration JSONL.
- Сейчас rubert_run2 RUNNING: PID27062, session97661, log
  ml/data/classifier_v2/rubert_run2.log. Полные12epochs,59416train rows,
  5258calibration views,312-dimensional embeddings. Не запускать дубликат.
- После чистого завершения Ruby автоматически стартует E5-small: wrapper
  train_queue.py PID27122/session70741 ждёт PID27062, проверяет calibration.json,
  затем запускает e5_run1 (mean pooling, query prefix,12epochs). Лог будущего
  запуска ml/data/classifier_v2/e5_run1.log. Параллельных fit на MPS нет.
- Файлы, влияющие на fit, зафиксированы на старте; не редактировать train/network/
  calibration/data/text/weak_labels/taxonomy/v1augment до окончания этих run.
  Другие модули, тесты, отчёты можно писать. Final holdout ещё НЕ оценивался.
- Тесты:218Python PASS до последних4label cases; новые label tests29PASS.
  Discovery tests в штатном окружении5PASS+1SKIP (нет sklearn), в train-env
  все6PASS с настоящим HDBSCAN. Полный Go vet/test PASS на текущем backend.
- Открытая реализация discovery предлагает кластеры, не меняет taxonomy.
  Добавление требует явно подтверждённого документа категории и reviewer.
  Hidden-category experiment использует calibration-компании для кластеров,
  отдельные test-компании для оценки после добавления; не строит прототип
  из тех же тестовых точек, на которых измеряется качество.

## Возобновление 15:46 МСК

- Пользователь написал «продолжай» после прерывания. Ветка ml, текущий commit
  2762e1a + рабочие изменения; исходные untracked SPEC/models/.claude/case
  сохранены. Deadline нет, задача v2 остаётся активной.
- run2 и его очередь были остановлены до завершения: дополнительный тест
  обнаружил, что старое жадное удаление VAT-хвоста могло удалить следующий
  payment-channel marker. Исправлено ограниченной грамматикой VAT; нормализация
  version v2-preserve-payment-channel-2, auxiliary teacher v2.3. Проверены
  payroll/fuel-card vs acquiring, incoming acquiring net of bank fee и НДС.
- Текущие данные prepared_v3:59903train/5395calibration views/50148test.
  Новый frozen182 и старый novel280 НЕ оценивались и не менялись.
- rubert_run3 ЗАВЕРШЁН (PID27713/session44510 больше не активны),12epochs,
  selected epoch12,1610s active training. Calibration category .9968489342,
  macroF1 .9953622643, channel .9985171455, tags после calibration .9977962011.
  source-hash guard прошёл. selected/ содержит обученный encoder, heads, config.
- Автоочередь PID27747/session65738 запустила E5-small PID30469. На15:46 он
  наepoch3 batch100; wall clock включает длительную паузу хоста, активный elapsed
  ~2210s. Не запускать дубликат. e5_run1.log/selected/history сохранены.
  Его fit_files включают model.py: до завершения НЕ менять model.py и остальные
  train/network/calibration/data/text/weak_labels/taxonomy/v1augment.
- Pending после окончания E5: при явном override runtime надо возвращать версию
  с суффиксом backend и использовать соответствующую calibration из runtime
  comparison; сейчас config.model_version не различает override. Исправить
  loader и тесты после завершения fit, без повторного обучения.
- Runtime/export тест с настоящим tiny random BERT прошёл, включая ONNX
  float32/int8 и динамические размеры/паритет. Это smoke, не метрики модели.
  Полный pytest248PASS+1SKIP до последних benchmark/runtime/export tests.
  buf lint через go run github.com/bufbuild/buf/cmd/buf@latest завершилсяPASS.
- В живом main-server с Torch после LightGBM первый v2RPC завис (deadline20s),
  v1/models продолжали отвечать. Native sample показал две libomp copies.
  Наш PID29285 после TERM пришлось KILL. Добавлен conditional Torch bootstrap
  ДО forecasters; штатный v1/ONNX не импортирует torch. Проверка исправления
  была прервана, сейчас запущена заново на50074; log torch_server_smoke_fixed2.
  Это только наш тестовый сервис, остановить после проверки.
- Новые Docker optional extras encoder/encoder-torch и исключение models из
  build-context подготовлены; обученные веса не будут включаться в Git/context.

## Сервис и freeze политики выбора, до итоговых тестов

- Ruby экспортирован в rubert_candidate1, версия encoder-v1-689ac3623ffb6316.
  Torch/ONNX-fp32/ONNX-int8 имеют одинаковые category/channel decisions на5395
  calibration views; max abs embedding difference float ONNX2.1e-7,int8~.0146.
  Tag microF1 .997796(float) vs.997691(int8). Выбран int8 по заранее заданным
  calibration parity bounds и скорости. Это ещё не окончательный encoder choice.
- Полный CPU batch256 (все нормализованные входы различны): median.1256s,
  p95.1630s,max.1674s,10повторов. Включены normalization/tokenization/encoder/
  heads/dicts/attributes; startup/network исключены. Локальная проверка M1Pro,
  E5 training ещё активен; не объявлять production SLA.
- Порядок импортов Torch/LightGBM не устранил native сбой: bootstrap дал139.
  Не оставлять этот workaround. Вместо него PyTorch работает в отдельном
  subprocess с bounded framed stdio IPC, без LightGBM. Parent остаётся numpy/
  LightGBM/gRPC. v1/forecast и ONNX не импортируют Torch. Попытки и native sample
  сохранены локально, bootstrap-файлы удалены (наши неопубликованные).
- Live isolated Torch smoke PASS:4concurrent v2RPC, v1supplier, настоящий
  gbm_global forecast8paths×7days. Worker был убит специально, следующий v2RPC
  восстановил его:PASS. Parent и worker после smoke остановлены,50074свободен.
- Изолированный regression test с tiny random BERT:ONNX+Torch load/parity,
  dynamic lengths,new prototype,worker crash/recovery и fresh main-server
  с v1/forecast PASS за33s. Он выполняется в отдельном subprocess, чтобы
  optional Torch не попадал в уже импортировавший LightGBM pytest-process.
- Штатный pytest250PASS+2SKIP до новых report acceptance tests. Все backend
  проверки ранее PASS. Source hashes E5 перепроверены:изменений fit sources0.
- Политика encoder choice фиксируется до финальных тестов: score=categoryAcc+
  .15*categoryMacroF1+.05*channelAcc+.05*tagsMicroF1 на законченных Torch
  calibration artifacts; tie<=1e-6 выбирает меньшие encoder weights. Это та же
  структура objective, что при checkpoint selection, с калиброванными тегами.
  Реализовано select_model.py; нужны ДВА завершённых run, не сравнивать Ruby
  на финальных тестах пока E5 не закончен. Старый novel и новый182 НЕ открыты.
- Pending после E5: унифицировать verified loader с encoder_factory и runtime
  override calibration/version (убрать временную дубликацию проверки из
  serving/torch_process.py). Файлы model.py/fit sources до конца E5 не менять.

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

## Проверки перед открытием финальных наборов, 16:25 МСК

- E5 PID30469 продолжает единственный fit, epoch5; очередь PID33657
  ml/data/classifier_v2/post_train_queue.py/session3574 ждёт calibration.json.
  Она автоматически зафиксирует encoder_selection.json из двух завершённых
  Torch run и запустит hidden_run1 (leasing,enforcement) с чистых pretrained
  весов выбранной семьи, той же recipe12epochs. Не создавать дубликат.
  Статус: ml/data/classifier_v2/post_train_state.json. Старый parent27747 жив.
- Fit sources не редактировать ДО ОКОНЧАНИЯ E5 И hidden_run1, включая model.py
  и calibration.py: source-hash guard завершённого run должен пройти.
  После обоих fit запланированы loader consolidation/runtime override и
  post-fit novelty calibration. Переобучение из-за этих изменений не нужно.
- До итоговых предсказаний input-only audit выявил4 точных нормализованных
  совпадения frozen182 с train (пустые/мусорные V2-153,154,155,164). Сохранён
  исходный SHA frozen; evaluator отдельно покажет178 входов без совпадений.
- RAW global distance threshold давал55.3% false novel внутри известного other
  на calibration при~5% overall. До final/hidden evaluation подготовлен
  novelty.py: rank расстояния относительно calibration-предсказанного класса,
  min_group30, fallbackglobal для редких/новых классов, threshold.95.
  Только known calibration использована; это геометрический rank, не posterior
  неизвестного класса и не внешняя гарантия FPR. Диагностика Ruby: overall4.82%,
  other6.38%. Интегрировать в calibration/model/export ПОСЛЕ обоих fit.
- Исправлен протокол hidden discovery ДО его первого запуска: кластеризация
  получает ВСЕ calibration-операции, включая ложные novel известных классов;
  нельзя предварительно отбирать hidden gold. Oracle labels используются только
  для симуляции называния уже полученного кластера, test остаётся отдельным.
- Исправлена идентичность артефакта: nested encoder/config.json теперь влияет
  на model_version; раньше исключение корневого config по имени захватывало
  вложенные файлы. Новые версии будут запечатаны после окончательного export.
- Targeted tests: selection/report8PASS; discovery/hidden/report11PASS+1SKIP;
  novelty9PASS. Предыдущий полный train-env pytest260PASS. Final holdout и
  hidden predictions всё ещё НЕ оценивались. Никакого live сервиса не оставлено.
- В workspace появились внешние untracked ml/zavozik_ml/trx/ (16:17–16:19);
  это не наша работа, не менять и не включать в classifier-v2 коммиты.

## Изоляция исходников следующего fit

- Для queued hidden fit сделана точная копия пакета без изменений в
  ml/data/classifier_v2/training_snapshot_v1; все training_files_sha256
  сверены с E5. ML_DIR внутри этого subprocess указывает на snapshot, поэтому
  source guards проверят именно неизменяемые fitting sources. Данные/база/out
  остаются прежними явными путями. Рецепт и encoder choice не менялись.
- Waiting queue33657 остановлена (не E5) и перезапущена как PID34739,
  session36339. Только hidden subprocess получит PYTHONPATH snapshot.
  После окончания E5 можно редактировать оригинальные model/calibration/
  train/export, не нарушая provenance продолжающегося hidden fit.
- В ml/data/classifier_v2/runtime_staging готовятся эти runtime изменения;
  пока они НЕ применены к рабочему пакету. Новые loader/calibration unit6PASS:
  backend override использует свой calibration и version suffix, отсутствие
  веса/графа/override calibration в manifest отказывается до запуска encoder,
  rank calibration/runtime согласованы. Staging tests не являются final eval.
- Полный штатный pytest после последнего коммита269PASS+2SKIP. Отдельные
  benchmark/report/hidden tests7PASS. В benchmark Torch CLI включён worker IPC,
  чтобы окончательная CPU-цифра соответствовала фактическому serving пути.
- Добавлено исключение root tokenizer.json neural releases: E5 tokenizer16MiB,
  не должен попасть в Git. Metadata/manifest остаются видимыми для публикации.
- Staging revision также прошла настоящий random-BERT export/Torch/ONNX/worker
  integration (1PASS,43.45s). Никаких final datasets эта проверка не использует.
- install_runtime_after_e5.py/session42396 автоматически дождётся успешного E5
  и старта hidden из snapshot, сверит исходные SHA, применит ровно5 staged
  source files + runtime tests и запустит targeted v2 suite. Статус/лог:
  runtime_install_state.json/runtime_revision_tests.log. При FAIL остановиться
  и изучить причину; не запускать повторный fit. Snapshot hidden не меняется.
- fetch_base теперь исключает собственный base_source.json и незавершённые
  .partial из source manifest. Повторный fetch pinned cache даёт тот же SHA
  manifest; сетевой mock regression test1PASS, actual downloads не повторялись.

## MPS resource recovery и новый checkpoint, 16:41 МСК (актуально)

- e5_run1 НЕ завершён. После epoch5/начала6 прекратил выдавать очередную
  отметку100 batches на12+минут (раньше~70s). sample/vmmap: footprint12.5GiB,
  peak13GiB на16GiB M1Pro, ожидание Metal command buffer и сильное давление
  памяти. Последний selected checkpointepoch4 сохранён, не объявлен completed.
  Причина записана e5_run1/STOPPED_RESOURCE_PRESSURE.json. Frozen182/novel280/
  company test всё ещё НЕ запускались. Это инфраструктурный restart, не подбор
  по финальному тесту.
- Остановлены только наш старый E5 PID30469, waiting queue34739 и
  installer35210. Старыйparent27747 также завершился после остановки child.
  Сессии36339/42396/65738 устарели, не возобновлять их и не запускать старые
  post_train_queue.py/install_runtime_after_e5.py повторно.
- Новый единственный fit PID35854/session83066:
  e5_run2_bs64_fixed.log, out e5_run2_bs64_fixed. Тот же pinned E5-base,
  prepared_v3,seed42,loss/LR/optimizer/batch64/12epochs. Исполнение из
  memory_bounded_snapshot_v2 (полная локальная копия source), где MPS сохраняет
  fixed padding128,LOW_WATERMARK=.7/HIGH=1.0 и освобождает free cache каждые100
  batches. Mask/токены/loss прежние. CPU random-BERT active-token parity
  maxdiff5.96e-8; добавлен regression в optional export test.
- Новый fit первые100 batches прошёл за167.8s, live allocated1.762GiB,
  driver7.131GiB после очистки. Следить за дальнейшим ростом памяти, не запускать
  ещё один fit. Ограничения allocator по официальной документации PyTorch:
  https://docs.pytorch.org/docs/stable/mps_environment_variables.html
- Новая очередь PID35915/session69644 — post_train_queue_v2.py. Она ждёт
  e5_run2_bs64_fixed, сравнит с completed rubert_run3, заморозит selection и
  запустит hidden_run1 из ТАКОГО ЖЕ bounded snapshot. Состояние в прежнем
  post_train_state.json. Selection/hidden пока не существуют.
- Теперь МОЖНО редактировать рабочие model/calibration/train/export: оба fit
  используют immutable snapshot, их source guards не зависят от текущего пакета.
  НЕ менять memory_bounded_snapshot_v2 во время fit.
- Применены новые core/runtime: category-conditional novelty rank, override
  runtime calibration+version suffix, общий manifest-verified loader с
  encoder_factory; server Torch helper делегирует ему проверку. Tests34PASS
  включая новый runtime, output, novelty и real Torch/ONNX subprocess smoke.
- В final export передавать --fit-source: для выбранного Ruby
  ml/data/classifier_v2/training_snapshot_v1; для E5 и hidden
  ml/data/classifier_v2/memory_bounded_snapshot_v2. В артефакт добавится fit_source
  с exact training_files_sha256; эти Python-файлы — исторические данные,
  runtime их НЕ импортирует. Новые train checkpoints архивируют source сами.
  Archive/runtime targeted13PASS+1SKIP в prod env. Финальные graph exports
  с rank calibration пока НЕ выполнены.
- Полный train-env pytest session32323 идёт в изменяющемся workspace, где
  внешний test_trx.py импортирует Torch в parent pytest. При native-конфликте
  не править trx: v2 optional tests выполнять отдельно, штатный полный prod
  pytest по-прежнему обязателен. Внешние untracked trx/runs/tests не коммитить.
- Этот полный train-env pytest остановлен: native sample36146 показал deadlock
  Torch linear ->libomp join barrier после импорта внешнего test_trx.py; CPU0%,
  одинаковые стеки. Sample сохранён full_pytest_native_sample.txt. Это тот же
  класс конфликта, который сервер v2 уже исключает изоляцией Torch worker.
  Новые проверки: train-env с --ignore=tests/test_trx.py (session9238),
  полный prod-env (session67953). Не менять чужой trx ради этой проверки.
- Проверки закончились: prod full277PASS+3SKIP за16.04s; optional train-env
  full без внешнего trx279PASS за43.78s (единственный HDBSCAN FutureWarning).
  Включены real export, masked-padding parity, worker recovery и live server.
- e5_run2 прошёл200batches за331.9s, driver7.131GiB после cache release,
  allocated1.762GiB — повторного роста памяти пока нет. Это единственный fit.
- Создан heartbeat classifier-v2, ACTIVE, каждые30минут в ЭТОМ чате: продолжает
  разрешённую задачу до deliverables, без дедлайна; не дублирует fit, молчит
  при неизменившемся состоянии, выключается после итогового отчёта. Старый
  overnight ml-07-00 не восстанавливать. Приложение/машина нужны включёнными
  для локальных запусков. Автоматизация использует существующий контекст.

## Пользователь вернулся: критика переобучения и аудит calibration

- Пользователь справедливо оспорил высокую accuracy. Проверены только train и
  calibration, final test/novel/authored по-прежнему НЕ открывались. Итог:
  ml/reports/metrics/classifier_v2_calibration_template_audit.json (агрегаты,
  хэши источников, без сырых операций). Обязательно включить эти ограничения
  и числа в итоговый classifier_v2.md; не подавать99.7% как real-world accuracy.
- В5395 calibration views всего1395 clean deduplicated real rows и4000
  perturbations из тех же calibration rows. Между train/cal компании не
  пересекаются, но нормализованные тексты/экономические шаблоны пересекаются.
- Clean calibration:530/1395 (38.0%) ПОЛНЫХ нормализованных входов уже есть
  в train;1282/1395 (91.9%) имеют существующий dedupe template. В full46137
  calibration operations45739/46072 (99.28%) непустых назначений имеют ту же
  пару direction+normalized-purpose, что в train. Это НЕ99.3% полностью
  одинаковых модельных входов: название/тип/бакет суммы могут отличаться.
- RuBERT clean calibration без пересечения dedupe template:113 примеров,
  111correct=98.2301%, но только5категорий (supplier79,revenue_b2b18,refund14,
  own_transfer1,other1). Этого недостаточно для оценки всех20 категорий.
- Эти результаты доказывают слабость протокола оценки обобщения, но сами по
  себе не доказывают классическое train-only overfitting. Нужны окончательные
  frozen new formulations + hidden categories и независимая human-gold проверка.
  Не менять текущие frozen наборы после просмотра; не подбирать по final.
  Сейчас fit продолжается как сравнительный эксперимент; дополнительные эпохи
  не решают проблему независимости оценки. Никаких новых fit не запускать
  только ради улучшения этих proxy calibration цифр.

## НОВОЕ УКАЗАНИЕ: сначала company+template-disjoint split (17:10 МСК)

- Пользователь прямо потребовал исправить разбиение ДО переобучения. Остановлены
  E5 PID35854/session83066 и queue35915/session69644; все старые run/queue
  оставлены историческими, не возобновлять. Heartbeat classifier-v2 обновлён.
  Старые модели/rubert_run3/любой prepared_v3 не участвуют в новом сравнении.
- Реализованы splitting.py и новая data.py. Начальные компании90/30/30 сохранены,
  шаблонные семейства назначаются одному partition; остальные вхождения purge.
  Группировка не использует model predictions: structural slots dates/docs/
  sums/periods/payment rails, lexical slots товаров/услуг/банков/регионов из
  existing v1 augmentation dictionaries; raw aliases для опечаток; transitive
  near duplicate families SequenceMatcher>=.90 и3gram Jaccard>=.65.
  Weak-label stratification используется только при назначении семейств;
  statistical missing-purpose targets ПЕРЕСЧИТЫВАЮТСЯ после purge по retained
  partition. Тест доказывает, что удалённый контекст не влияет на empty targets.
- Train augmentations сохраняют parent_id/company/family; synthetic и perturb
  строки, совпавшие с heldout raw/masked/near family, отбрасываются. Primary
  calibration/test только case_weak, без4000 calibration perturbations.
- Prepared_disjoint_v1/v2 были только стадиями разработки группировки, без fit
  и без model predictions. ОКОНЧАТЕЛЬНЫЙ frozen dataset:
  ml/data/classifier_v2/prepared_disjoint_v3, protocol company_purged_template_families_v3.
  train56502rows/47700inputs (после augmentation), real train105803rows/128families;
  calibration211 clean deduplicated rows/36families, calibration_full2251rows;
  test5561rows/643inputs/39families. Исходных операций222420, retained113615;
  purged108805. Нельзя делать вывод о числе независимых наблюдений по rowcount.
- Post-augmentation audit: ВСЕ pairwise company/family/canonical/raw input/
  dedupe key/near-template intersections равны0. Для обоих реальных tokenizers
  дополнительно0 пересечений128-token inputs, включая префикс query E5.
  Воспроизводимый token_audit.py, SHA+prefix+revision+maxlength guards в train.
  Команды и ограничения обновлены в classify_v2/README.md.
- Public aggregate/audit/protocol/coverage (без сырых операций):
  ml/reports/metrics/classifier_v2_disjoint_split.json. Manifest SHA
  348227be9e04a473f7ad741199f1c09f7936b6d8128e2eb540be4b339aed31c7,
  trainSHA a38b7c76aa962271ac30c98af8dcbe0d1e84d7883cfda350925543e5ed7fcba5,
  calSHA4f58d13423c18f836d4c39cbe853f87a4a2a20d33403c842a35278a09354587f,
  testSHA273afddb5ccb3a58872dfeac34ff9a05995ef2789d306b91460c3525167ba9a5.
- Coverage честно ограничено: calibration12/20категорий и2/8канала; test15/20
  и3/8канала. Не генерировать faux-gold для заполнения пробелов. Report теперь
  показывает неподдержанные категории и family macro accuracy; отсутствие
  категорий в company test не позволяет объявить всю приёмку пройденной.
- baseline.py переобучает linear-v1 на ТОЧНО ТОМ ЖЕ prepared train (без своей
  дополнительной аугментации), clean cal только для температуры. Released v1
  не меняется. evaluate/select отказываются смешивать разные training pools,
  registry или старый протокол. export для timing берёт реальные cal_full
  inputs: чистых211 меньше256, cal_full362unique; после hide rent/utilities341.
- Hidden experiment ДО любых новых model predictions зафиксирован как
  rent,utilities: у них есть≥5 cal discovery и≥5 test rows. Leasing/enforcement
  не имеют cal-покрытия после purge, симулировать их успешную проверку нельзя.
  Discovery/test разнесены и по компаниям, и по template families.
- Tests: splitting9PASS, selection5PASS, token guards2PASS; полный prod290PASS
  +3SKIP; optional train-env292PASS (без чужого trx), HDBSCAN FutureWarning only.
  Ни один новый model fit до завершения этих проверок не начат.

## Новый pipeline запущен ПОСЛЕ аудитов, 17:15 МСК

- Commit4a3b6b3 фиксирует split/protocol/audit до новых model predictions.
  Root ml/data/classifier_v2/disjoint_v3_runs, immutable full package snapshot
  source_snapshot (исключён чужой trx), experiment_protocol.json содержитSHA/
  sourcecommit/рецепт/hidden choice. Snapshot НЕ РЕДАКТИРОВАТЬ во время fits.
- Единственный controller PID38250/session1244:
  ml/data/classifier_v2/run_disjoint_v3_pipeline.py. Атомарный статус в
  disjoint_v3_runs/pipeline_state.json, лог controller disjoint_v3_pipeline.log,
  каждый step в root/STEP.log. Не запускать этот script повторно: existing
  root защищён от дубликата. Не возобновлять ни одну старую очередь.
- Pipeline САМ делает по порядку: input-only audit frozen182 (без предсказаний),
  baseline refit -> Rubert12epochs -> E512epochs -> cal-only selection -> fresh
  hidden rent/utilities12epochs -> main/hidden export -> CPU benchmark -> ОДИН
  final evaluate с новым baseline -> novelty experiment -> report. После этого
  статус evaluations_complete_review_required: агент проверяет ошибки/ограничения,
  live v2/v1/GBM, model card/immutable publication, финальные проверки/коммиты.
  Не дублировать автоматические этапы, особенно evaluate после lock/результатов.
- Linear baseline уже ЗАВЕРШЁН:56,502train rows из того же prepared файла,
  clean211cal; L-BFGS сошёлся за88итераций,48.5s. Это cal agreement с weak labels,
  НЕ real-world accuracy (веса/meta/calibration в root/linear_baseline).
- Сейчас Rubert PID38362, fresh pretrained/base, source snapshot. E5 ещё НЕ
  запущен: только sequential fitting, не создавать параллельный дубль.
- Heartbeat classifier-v2 обновлён на этот controller/root. Когда pipeline
  running, читать только актуальный статус/лог и делать независимую полезную
  работу; при failed разбирать точный step, сохранять completed fits и не
  повторять train/consumed final evaluation. Никакого tuning по final.
- Примечание: export timing использует362 genuine cal_full inputs (341 после
  hide), поскольку primary clean211 меньше256. Label/temperature calibration
  остаётся на211 clean rows; это не добавление noise в оценку качества.

## Прямое уточнение пользователя: ВСЕ категории обнаруживать из векторов

- Пользователь выбрал второй вариант: модель сама находит смысловые группы и
  формирует ВЕСЬ справочник, а не выбирает из20 категорий. Это отменяет fixed
  taxonomy/category CE часть исходного ТЗ; актуальный план в
  docs/CATEGORY_DISCOVERY_DESIGN.md. Не возвращаться к supervised20 без новой
  прямой просьбы пользователя.
- Проверены command lines и остановлены ТОЛЬКО наши controller38250 и
  train child38362. disjoint_v3_runs/pipeline_state.json и
  STOPPED_ARCHITECTURE_CHANGED.json фиксируют причину. Старые fits сохранены,
  E5/hidden/export/final этого pipeline не начинались. Heartbeat обновлён.
- Новый package category_discovery: real-only label-free corpus, pinned
  pretrained E5 (без fine-tuning по слабым меткам), HDBSCAN по независимым
  семейным medoids отдельно in/out, автоназвания из characteristic terms,
  версии/ID, geometric abstention, incremental auto categories без изменения
  прежних ID. Никаких named seed prototypes или заданного числа категорий.
- Новый corpus_v2 в ml/data/category_discovery: реальные train105803ops/
  385unique purposes/128families; calibration2251/81/36; test5561/80/39.
  Повторы не увеличивают independent density. При подготовке не вызываются
  Go/teacher/augment; старые labels не читаются. Ownership унаследован от v3:
  факт его исторической weak-label stratification записан в manifest.
- e5_embeddings_v2: реальные128token input intersections ВСЕ0. Train/cal/test
  embeddings вычислены одним pinned encoder, без обучения на test. Пока ни
  одной final category prediction нового решения не было. Corpus_v1 и
  embeddings_v1 только предварительные preparation checks; fit не запускался.
- Новый отдельный gRPC categorize.v3 DiscoveryService, так как динамический
  справочник/возможный unassigned/геометрические scores не совместимы с
  обещанием старых category_probs. Go-генерация/Go/backend не менялись.
  Separate CPU process без LightGBM; channel/tags отдельно из weak rules,
  экономические mandatory/flow неизвестны без независимой проверки.
- Добавлены frozen experiment protocol/one-time evaluate и локальная слепая
  pairwise review без предзаполненной разметки. Никакую coverage/silhouette/
  stability не выдавать за semantic accuracy. Auto titles — черновики.
- Дальше: tests -> commit протокола ДО fit -> единственный experiment_v1
  на corpus_v2/e5_embeddings_v2 -> один final transfer audit -> blind review
  -> CPU/live service и immutable model card/artifact -> final checks/report.
  Не обещать независимое semantic качество без человека; это research status.

## Иерархия по прямому выбору пользователя и frozen baseline — 17:46 МСК

- Пользователь ответил: «Иерархия: крупные группы и подгруппы». Добавлены
  train-only complete-linkage tree, coarse cut в поздней половине merges,
  category_path/coarse ID/hierarchy_version в v3 RPC. Начальный full-gap cut
  давал13coarse, новый coarse-view cut7; данные test не выбирали cut, листья
  и frozen assignments не менялись. Старый tree сохранён hierarchy.json,
  итог hierarchy_v2.json. Для каждой суммы выбирается один уровень агрегации.
- Commit0321172 зафиксировал новый label-free fit до эксперимента. Единственный
  experiment_v1 завершён:130independent family×direction points,41noise,
  16листьев (5in/11out). Нет обученных по категориям весов или их weak targets;
  E5 pretrained frozen, train используется для групп/геометрии. Не перезапускать
  fit или finalevaluate: он УЖЕ ПОТРЕБЛЁН, final_evaluation/evaluation.json.
- Train silhouette .2723017. Family subsample ARI на jointly-clustered .730–1;
  Jaccard .831–.920. Это internal geometry, НЕ semantic accuracy. Test:
  43/80unique assigned53.75%,1759/5561operations31.631%,familymacro49.023%;
  29outside/5ambiguous/3empty unique. Calibration51/81unique62.96%.
  semantic_accuracy=null. Есть смешанные кластеры и слабые auto names;
  никаких заявлений о готовом бухгалтерском справочнике.
- Построен полный tree32nodes,7coarse,16leaves. Leaf taxonomy
  discovered-v1-ca0d2cfcb5ea99563cb8; hierarchy-v1-f8740ce139bd8a49bb48.
  Корни in/out — факты направления; все экономические title extractive.
  Coarse-only assignment и вероятности правильности НЕ реализованы/не доказаны.
- Опубликован self-contained immutable RESEARCH bundle
  ml/models/classifiers/discovery-v1-dbedf812a8a62d450b9f с encoder/base hashes,
  inventory/manifest, hierarchy, release.json, историческими fit_source и
  hierarchy_source, model card. Release loader проверяет все payload hashes.
  Encoder493292987bytes, whole493410066bytes. Encoder/ ignored; вGit только
  metadata/карта/history, не добавлять веса. Предыдущий неsealed draft ТОЛЬКО
  нашего создания перемещён в ignoreddata/unsealed_release_draft_v1.
- Actual CPU gRPC benchmark:256distinct train purpose inputs,5reps,4threads,
  median.53982s,p95.55440s,max.55676s. Включены RPC/encode/tree/weakaux, без
  startup и без embeddingcache. CPU/MPS maxdiff2.6124e-7,assignment mismatch0.
  4concurrentRPC PASS. Sealed final bundle дополнительно actual loaded/RPC/
  tree32nodes/7coarse/blankabstention/optionalunknown counts PASS. Все наши
  временные gRPC processes после проверок остановлены. Colima не запускалась.
- Public report ml/reports/classifier_v2.md и aggregate
  ml/reports/metrics/category_discovery_v1.json. Реальные источники/тексты
  остаются ml/data/category_discovery. Базовый release-v1 forecast и Go не тронуты.
- Blind review:120different-company/template pairs (40same-cluster/40different/
  40unassigned), ни одного готового human answer. Offline page
  ml/data/category_discovery/blind_review_v1/review.html, без networkcalls и
  modelpredictions; revieweridentity,localstorage,exportJSONL. Не выдавать
  заполнение агентом/моделью за независимый human gold. Coarse-level смысл
  требует отдельной проверки. Сырые данные внешним API не отправлялись.
- Tests: production full300PASS+7SKIP; optional full306PASS с одним прежним
  HDBSCANwarning. Первый optional run без PYTHONPATH=.:gen упал ТОЛЬКО на
  child import categorize; исправлено окружение, отдельный export test1PASS и
  последующий full306PASS. Новые release/UI checks дополнительно6PASS+1PASS;
  final full ещё выполняется после новых тестов. Go test ./... и go vet ./...
  PASS на текущем mergedmain; buf lint PASS. Никаких Go изменений.
- На момент checkpoint нет активного fit/queue. Следующий необходимый шаг
  качества — независимая пара/кластерная разметка и отдельный developmentgold.
  Нельзя автоматически повышать «качество» повтором эпох/подгонкой по final
  или вернуться к остановленным20class queues. Учёт архитектурных вопросов
  решён: пользователь явно выбрал полностью найденный из данных справочник
  и иерархию. Осталась эмпирическая проверка экономического смысла и дальнейшее
  обучение/сравнение similarity на независимом development наборе.
- Final full checks после всех новых core/service/release/UI tests:
  prod302PASS+7SKIP за15.54s; optional308PASS за33.83s (прежнийHDBSCANwarning).
  Offline annotation JS syntax node --check PASS; source-escaping/no-prefills
  тест PASS. Новый ML_EXTRA=discovery использует CPU Torch index; default image
  unchanged. Linux image build не выполнялся, нужна server smoke проверка;
  Colima не запускать только ради повторения native integration.
- Heartbeat classifier-v2 удалён после доставки воспроизводимого research
  baseline/иерархии/артефакта/слепой проверки: активных fit/queue больше нет,
  необходимая независимая human оценка ещё не предоставлена. Не обещать
  продолжение unattended обучения и не запускать его вместо получения gold.
  Следующее пользовательское сообщение/предоставленная разметка продолжит
  ML quality работу; это не заявление о завершённой semantic приёмке.

## Запрос плана исправления экономических смешений

- Пользователь потребовал сохранить полностью обнаруживаемые категории и
  иерархию, исправить смешения и сначала представить план улучшения.
  Подготовлен docs/CATEGORY_DISCOVERY_IMPROVEMENT_PLAN.md. Runtime/fits/
  действующие артефакты в этом проходе не изменялись, heartbeat не создавался.
- Read-only train аудит: удаление одного money placeholder `сумма` сокращает
  385unique direction×purpose до196;12групп/32unique rows объединяют разные
  прежние family IDs. Calibration81→60unique. Это не новая подготовка и не fit.
- README источника явно говорит, что150компаний/222420операций СИНТЕТИЧЕСКИЕ.
  «Реальные строки» ранее означало source-case rows вместо added augmentation,
  а не настоящие банковские выписки. Прямо учитывать это в будущих отчётах.
- План: cleanup+new split audit -> экономические coarse/fine pair labels и
  проверенные hard negatives -> больше независимых назначений -> frozen
  E5-small/E5-base/Qwen3-Embedding-0.6B comparisons -> contrastive fine-tuning
  финалистов/semantic pair verifier -> semantic-validated hierarchy with
  coarse-only/unknown -> независимый test с coverage/precision/интервалами.
  Ни20классов, ни7/16групп не являются целевым числом. Новые модели ещё не
  скачивались; все результаты кандидатов/пороги/объёмы в плане — предложения.
- Обязательная зависимость качества: независимая экономическая разметка и
  новые разнообразные данные; проверенного внешнего корпуса в этом проходе
  не найдено/не скачано. Self-labels/LLM/paraphrases не human gold. Старый final
  исторический и не становится новым независимым test после переименования.

## Экономическая итерация v2 — 24.10, ~18:45 MSK

- Пользователь разрешил реализацию плана; в ответ на вопросы: human reviewer
  и новых выписок нет, продолжать research и искать публичные данные. Не
  останавливать полезную работу ради human gold, но не называть self-labels gold.
- Новые normalization.py/preparation.py отделены от старого sealed v1контракта.
  Суммы/НДС/реквизиты убраны; стадии отдельно; отрицания/роли/объект сохранены;
  пустой окончательный расчёт unusable. Старые v1/20class queues не запускались.
- Immutable corpus_economic_v4: label_free_company_template_token_closure_v2,
  purpose_evidence_query_v2. Source222420→372direction×text/369usable;
  train70590rows/223unique/222usable/102families;cal20141/81/81/22;
  devtest1966/22/20/20. Старые90/30/30companies, NEW label-free hash owners.
  Connected aliases/near/actualtoken closure ДОsplit; все пересечения0 у
  E5small/E5base/Qwen с их реальными prefixes/128/128/256 truncation. Эти
  families leakage guards, НЕ density point/semantic category. v3diagnostic
  отвергнут доfit, перемещён diagnostic_rejected_numeric_leakage_v3/REJECTED.txt.
- Frozen train/calibration cache_v2 готов для3models, finaltest не кодировали
  и не оценивали. Модели скачаны/провереныLFSsha: E5base d128750... MIT,
  Qwen3-Embedding0.6B97b0c614...Apache2. E5smallстарыйpinned. Размерности384/
  768/1024, корректные mean/last pooling и prompts. Runtime/Go не мигрировали.
  DownloadCDN resets56/18починил resumable retry; все downloadjobs завершены.
- Open authored economic_regressions.py14triplets: E5small8/14,E5base8/14,
  Qwen13/14(провал rent_purchase). Это agent-authored DEVELOPMENT DIAGNOSTICS,
  не accuracy/independentvalidation/selection. Не ретюнить frozenfinal по ним.
- semantic_pairs.py:1000train815cal105devtestblindpairs, coarse/fine/rationale/
  reviewer_kind; source/hashbound,2humanconsensus по умолчанию,agent votes
  исключаются, транзитивные конфликты не экспортируются вtrain. UI offline,
  sourceescaping, no network; actual IAB render/navigation PASS без ответов.
  Не считать пустые формы gold. evidence_graph.py — research forest complete
  verified cross-pair compatibility, noforcedroot/coarse-only/unknown/ambiguity;
  реального calibratedverifier ещё НЕТ, runtime не активирован.
- External source НАЙДЕН/СКАЧАН: официальный Spending.gov.ua CC-BY4.0,
  https://spending.gov.ua/new/en/about-portal . 2021-10-04raw50393rows55.47MB,
  sha e9480a0b...; qualified_v1 39497organization↔organization,4422payers,
  33984exactpurposes. ДанныеUKRAINIAN/MIXED PUBLIC BUDGET, auxiliaryresearch,
  не Russiancommercialgold. CompanyIDs hashed, names/accounts/amounts/KEKV
  omitted features, purpose может содержатьФИО, не обещать anonymization.
  ml/data/category_discovery/external/spending_2021-10-04_qualified_v1.
  rawdownload `.partial` завершён (имя не значит активный); weekend2021-10-02
  пустой. ДляAPI нужен --http1.1 --tlsv1.2 --tls-max1.2, сертификаты не отключали.
  Public portal curl403, licenseevidence сохранено как JSONexcerpt viaweb,
  не forgedHTML. public_transactions.py после qualify ужесточил проверку
  licenseevidence; v1artifact sourcehash соответствует прежней реализации;
  в новом проходе сохранить текущий source snapshot/новую qualifiedversion.
- nZiben/PaymentIntentClassifier имеет TSV/weakGPTlabels, repo licenseNone;
  вfit не включён. eovsianik/biv-hack-1MIT имеет маленький data/sample.tsv,
  ещё не загружен/не квалифицирован. Не исполнять чужие model.pkl/ноутбуки.
- Checks: prod342PASS6SKIP до последнего publicsource файла; focused42PASS.
  Full optional/финальные повторить после новых правок. НиGo/forecast/trx
  не менялись. Все новые sourcefiles покаuntracked; коммитить ТОЛЬКО свои.
- Сейчас начата установка mlx-lm0.32.2 в isolatedignored
  ml/data/category_discovery/teacher_venv (session84290), log install_teacher.log.
  План локального teacher mlx-community/Qwen3-4B-Instruct-2507-4bit,
  revision50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b,Apache2,baseQwen3-4B-
  Instruct-2507. Ещё НЕ скачан/не запущен. Не дублироватьустановку, сначалаlog.
  Любые его labels будут WEAK, не human. Сырые данные внешнимAPI не посылать.
- Собственный UI preview: http.server8874PID47835,session53185,bind127.0.0.1,
  IAB tab1(browserid2) временный; остановить наш сервер послеUIпроверки.
  Colima OFFне запускалась. Heartbeat не создан, activefitнет, дедлайна нет.
  Продолжить stagepublicdataprep/split+localweakteacher, не возобновлятьold20fit.
  Progressreport ml/reports/category_discovery_economic_v2_progress.md,
  metrics/category_discovery_economic_v2_progress.json. Дообучения ещё не было.

- ~18:50MSK: production344PASS6SKIP; optional350PASS(старыйHDBSCANwarning).
  UIserverPID47835остановлен, IABtesttabзакрыт. MPSjobs закончены. MLXteacher
  env установлен:mlx-lm0.32.2/mlx0.32.4, piploginstall_teacher.log. Единственный
  teacherweights download session2061,fetch_teacher.log,base teacher_base/
  50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b. Не дублировать, model.partial
  ~132MiBна18:48. Ещё НЕ generation/fit. Новая qualified_v2 сохраняет текущие
  preparation_source snapshots; в дальнейшем использовать её вместоv1.

## Продолжение ~18:58 MSK (не считать завершением)

- Commit8fe04eb сохранил предыдущую большую контрольную точку. После него
  добавлен public_corpus.py/test и local_teacher.py/test/teacher_diagnostics.py,
  модифицированы candidate_models/cache и semantic_pairs (покаuncommitted).
- Publicqualified_v2 готов с текущимsource_snapshot. Новыйpublic_corpus_v1
  УЖЕ ПОДГОТОВЛЕН, не повторятьclosure: bounded6000rows breadth-first companies,
  UnicodepurposepreservingUKletters, noKEKVtargets,hashcompanyownership60/20/20,
  near/numeric-leakage aliases/actual128/128/256tokenclosure before split.
  train3492rows/3454unique/2588companies/3205families;
  cal1091/1080/835/1022;devtest1142/1135/853/1081; всеintersections0.
  Metadata ml/data/category_discovery/public_corpus_v1/manifest.json,
  sourcecopy public_corpus_source.py.txt. Разбиение толькоheuristic template
  independence, не доказательство semanticindependence или Russianbankgold.
- public_pair_review_v1 УЖЕ СФОРМИРОВАН,1000pairsнакаждыйpart. Никакихответов.
  semantic_pairs теперь bounded reservoir sampling,неO(N²)storage; lexical
  sets cached. Старыеeconomic_pair_review_v2 immutableне менялись.
- ЕДИНСТВЕННЫЙ GPUjob сейчас public CandidateCacheQwen: session98283,PID50967,
  logfilepublic_cache_qwen.log, outpublic_candidate_cache_v1/qwen3-embedding-0.6b.
  Он кодируетТОЛЬКОtrain/cal,no devtestread. На18:58run~3min,не дублировать,
  не запускать другиеMPS/MLXjobs покаон не закончит.
- Teacherdownload session2061,PID49627 ещёактивен,fetch_teacher.log;
  weights expected2263022417bytes,на18:58~1.9GiB. Кодfetch_teacher pinned,
  LFSSHAverify mandatory. tokenizerfilesбудутпослевесов;не load доteacher_source.json.
- MLX API проверен черезinspect вteacher_venv: mlx_lm.load(localpath,
  trust_remote_code=False,tokenizer_config={local_files_only:True,...});
  generate(...,max_tokens256,sampler=make_sampler(temp=0)).
  local_teacher.pyresumablewithfilelock/perpairatomicfiles/exactevidencespans,
  rejectsbadJSON/hierarchy/changedinputs,ALWAYSlocal_model_weak nothuman.
  Егоsource/protocol ДОЛЖНЫБЫТЬзафиксированы доfirstgeneration. Очередьне запущена.
- teacher_open_diagnostics_v1_inputs создан(28pairs из14openauthoredtriplets,
  private_expected.jsonl). Сначала boundedteacher_diagnostics.py послеweights
  иQwencache, outteacher_open_diagnostics_v1. ЭтоdebugНЕgold/НЕtraining.
  Послеpilotизучитьschema/evidencefailures/экономическиеошибки/runtime;только
  еслиосмысленно,запускать boundedweakannotation public_pair_review_v1 train/cal.
  Не teacherannotate devtest/frozenoldfinal. Не называтьselflabelsindependent.
- Новыеfocusedtests normalizerUnicode3PASS,teacherparser4PASS,semantic+candidate
  вместе12/13PASS. Текущийprod fullsessionбудетпроверенследующимпроходом.
  UIserver ужеостановлен. ColimaOFF. Нетheartbeat/новыхthreads/subagents.
  Пользовательявноотказался отhumanreviewпока ипроситискатьpublicdata; незадавать
  опятьэтиже вопросы. ПродолжатьMLresearchбездедлайна,неостанавливатьсялишьиз-заgold.

## Активная длинная очередь — 24.10 ~19:22 MSK

- Все изменения сохранены:8fe04eb,49fa182,bc40d00,77173d6,2186a6c,0f74f98.
  Безpush/Co-Authored-By;origin мог обновляться извне, мыpushне делали.
- Сейчас ЕДИНСТВЕННЫЙ controller research_public_v1: execsession2788,
  PID52801; childteacherPID52813 настарте. Данные состояния
  ml/data/category_discovery/research_public_v1/pipeline_state.json,
  config.json, source_snapshot. Rootlog research_public_v1_controller.log,
  step teacher_train.log. На19:21teacher44/1000, работает. НЕ ДУБЛИРОВАТЬ.
  Controller сам: teachertrain1000/cal500 ->metricheads3models seed42 ->
  calibrationoriginal/centered/adapted -> freezeweakcalAPranking ->43/44seeds
  лучших2. Финальнаяphase fits_complete_review_required. Это НЕ allworkdone.
  Childenvcwd=runroot,PYTHONPATH=immutable source_snapshot;fitprovenancecommit
  0f74f98. СнимокНЕ МЕНЯТЬ. Всеinput/featureSHAпривязаны;failedstepсмотретьточно,
  сохранятьготовыеfits,возобновлятьтолькоunfinished. Batchteacherresumable,
  fitpartiallyfailedнеперезаписывается,нуженразборпричины. Никакогоfinalread.
- TeacherлокальныйMLX4bitскачанполностью/проверенLFS:2263022417bytes,50d427...;
  envteacher_venv,mlx-lm0.32.2/mlx0.32.4. Все modelinferenceoffline.
  Первоначальный promptv1 оказалсяплохим:24/28schema,всеcoarse=same,
  только18/28openexpectations. НЕ использоватьегоlabelsдляfit.
  Promptv2уточняетэкономическуюобязанность/роль вместоanycommonancestor.
  Opendevdiagnosticv2:25/28schema,23matched/25valid,3invalidrelationvalues;
  этоНЕaccuracy. Creditpositiveимелошибочныйoutdirectionвauthoreddiagnostic,
  helperисправленпослеv2; невыдаватьэтуошибкуданныхзапровалмодели. Website
  refinement/developmentпараостаётсяспорной поfineгранулярности. Не ретюнить
  бесконечнопромптпод14opencontrasts. Послеv2полнуюдиагностикунеперезапускали.
- ВАЖНО teacherтеперьвидиттолько row.side.semantic_text (тотжеinputстудента),
  НЕ исходныеbudgetcodes/скрытыепризнаки. Evidenceстрогоsubstringэтоговида.
  Public_pair_review_v2пересобранДОразметкиизтого жеimmutablepubliccorpus:
  1000первыхstratifiedreservoirpairsнаpart,endpointдобавленsemantic_text.
  public_pair_review_v1неиспользоватьдляучителя(внёмнетэтоговида).
- Serialpublicteacherpilot64закончился:49schema-valid/15invalid,
  coarse22same/27different,fine15same/34different,275.37s.
  Invalid12неправильныхrelationvalues/3evidencenotliteral. Ониотбрасываются,
  не исправлятьугадыванием. Этоweaklabels,неhumangold/непроверкаточности.
- Batchsmoke8закончен:7valid/1invalid,30.32s,3.47GiBpeak;seq32.55sнасамех8.
  Увсех7validcoarse/fineсовпадают,invalidтотже. parity.jsonсохранён.
  Batchingнеобещаетогромногоускорения (~3.8–4.3s/pair),егоrecipeотдельный.
- Все3 PUBLIC train/cal featurecachesГОТОВЫ вpublic_candidate_cache_v1.
  QwenMPS3454train241.779s/cal1080=77.927s. E5small/baseCPUтожеcomplete;
  не кодироватьзаново. Train-only tokenbudgetaudit public_train_token_budget_v1:
  E5max81tokens(128budget),Qwenmax152(256budget),truncation0укаждого;
  увеличиватьконтекст/пересобиратькорпусрадигипотезыненужно.
- train_metric_heads.py — realCPUoptimizationдвухнезависимыхaffine+L2heads,
  encoder FROZEN (не fullfine-tune). БезcategoryCEиimplicitinbatchnegatives;
  coarsepositive/finenegativeдопустимы,uncertainmasked. <=6epochs,patience2,
  checkpointcal-only,по20same/differentкаждоголвлминимум. Weakopt-inявный.
  Приinsufficientlabelsupport НЕ понижатьмолчаgates:исследоватьsampling/data.
  NPZweightsбезpickle,dimсохраняется384/768/1024,serverнепереключали.
- metric_evaluation.py calibrationONLY:original/centered/adaptedAP,ROC,F1/
  thresholds. ЭтоapparentWEAKteacheragreement,НЕindependentprecision,
  balancedpairselectionНЕpopulationaccuracy,IIDintervalsневыдумывать.
  Необъявлятьцентровкууспехомобучения. Настоящийexternalgoldещёнет.
- Testsпоследнийprod354PASS7SKIP;optional357PASSбылдоновейшихtrainer/eval,
  новыеrealoptimization+evalfocused3PASS. Текущийlatestoptionalfullsession82001
  ещёпроверить;старыйHDBSCANwarningдопустим. Go/forecast/trxнетронуты.
- Созданheartbeat **idml**,nameЭкономические категорииML,каждые15мин,ACTIVE,
  currentthread(новыечаты/подагентыНЕсозданы). Этопродолжениеавторизованной
  работыбезdeadline,неполныйитог. Прифинальномисследовательскомзавершении
  удалить/выключитьidml;неповторятьстарыеclassifier-v2/ml-07-00ID.
  ИспользованOpenAIDocsдлясверкиscheduled-in-chatworkflow;файлынастроек
  /Users/beesknight/.codex/automations/ml/automation.toml. Другую06-32НЕтрогать.
- Нужныследомпослеочереди:разборреальныхweakmetrics/ошибок/seedstability,
  known-positive/negativechecksпослеадаптации(неfinal),semanticcategory/
  hierarchyprototypeсforest/coarse-only/unknownиCPU/runtime+modelcard.
  evidence_graph.pyпокаНЕподключёнкнастоящемуvalidatedverifier. Нетзаявлений
  обидеальности/независимойточности. Новые768/1024dimsнеобрезатьдонашего384RPC.
  Послеboundedresearchчестныйитог+чтоостаётсяпоML/Go;Goинтеграцияуbackendowner.

- Latestfulloptional послевсехновыхкода/tests:361PASS,прежнийHDBSCANwarning,
  38.32s. Prod354PASS7SKIP. Optionalrunсоздал4ранееотсутствовавшихcalendar
  cachesru2020..2023(birth19:21:50–51вовремятеста);толькоэтинашитестовыефайлы
  перемещенывignoreddata/category_discovery/test_generated_calendar_cache_20261024_1921.
  Forecastcode/trackedcalendarне менялись. На19:22controlleralive,teacher56/1000;
  UI/тестовыхсерверовнет. Автомацияidmlпроверена:ACTIVE/15min/этотthread.

### 2026-10-24 20:23 MSK — runtime sleep diagnosis

- Branch ml, tracked tree clean before this note; sole controller 52801 and local
  teacher 52813 remain alive, teacher_train 400/1000. No duplicate job or fit.
- Slow wall-clock progress is explained by macOS sleep: pmset records maintenance
  sleep 20:13:33–20:22:23, preceded by similar sleep/dark-wake cycles since19:47.
  Device on battery80%. A two-second native sample confirms active MLX/Metal
  inference after wake, not a known deadlock. No model failure in logs.
- Native diagnostic saved only in ignored research_public_v1/teacher_train_sample_20261024_2022.txt.
  Did not change system power settings or override lid/user sleep. Jobs resume
  when the host runs; wall-clock completion estimates are unreliable while asleep.
- Source snapshot/config/data untouched; no new calibration/model scores yet.

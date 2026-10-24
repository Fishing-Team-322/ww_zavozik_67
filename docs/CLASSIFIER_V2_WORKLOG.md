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

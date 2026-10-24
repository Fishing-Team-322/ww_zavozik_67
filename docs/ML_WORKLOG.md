# Ночной ML-прогон 24.10.2026

Дедлайн: 07:00 Europe/Moscow (04:00 UTC). Рабочая ветка `ml`.
Авторизация: подготовка данных, классификатор, проверка прогноза, ML gRPC и Go-клиенты. Остальной backend не менять. Без Co-Authored-By.

## Исходное состояние

HEAD 985c96f. Незакоммиченный классификатор агента восстановлен копированием выбранных файлов из `.claude/worktrees/agent-a023a2ffa0c927660`; исходная копия не изменена. 28 тестов классификатора прошли после сохранённого переобучения Claude.

## Выполняется

- Подготовка данных: сверка наблюдаемых остатков вместо эвристики 10 тихих дней; удаление повторов только при подтверждении остатком; дата обнаружения пропуска для причинного бэктеста. Проверки/экспорт запущены.
- Далее: независимый протокол оценки, сегменты короткой/неполной истории, отдельные цели account/business, дата/сумма/вероятность разрыва, соответствие Go.
- Далее: валидация gRPC, версии артефактов, ошибки/фолбэк, реальные интеграционные тесты Go↔Python и Docker.
- Дополнительные данные: использовать только подходящие открытые источники с проверенной лицензией/схемой; не скачивать большой нерелевантный MBD ради объёма. Не отправлять выписки внешним API.

## Важные ограничения оценки

Весь предоставленный набор — один синтетический генератор, а все компании ранее уже использованы Claude в экспериментах. Новый split не превращает их в никогда не виденный внешний тест. Старый novel classifier test тоже уже анализировался; считать regression/dev. Нужна отдельная независимая разметка для заявления о реальной точности. Ни одна новая метрика не должна называться гарантией безошибочности.

Прогнозная модель обучена на потоках бизнеса БЕЗ own_transfer/owner_loan, но С зарплатой/налогами/арендой. Не добавлять те же регулярные платежи поверх повторно. Внешние будущие события — зона коллег; контракт ML должен явно описывать scope.

## Автоматизация

Heartbeat `ml-07-00`, каждые 30 минут до 04:00 UTC. Продолжает тот же чат, без постороннего backend и без соавторства. После дедлайна/завершения выключить, если ещё активен.

## Контрольная точка 03:45 МСК

Сделано:
- Исправлен экспорт: 95 361 дневная строка, 150 компаний; удалены 20 подтверждённых остатковым балансом повторов, 1 неоднозначный сохранён, 936 дней отмечены по нарушениям сверки. Тихие праздники больше не считаются потерянной выпиской. `missing_known_on` делает историческую маску причинной.
- Восстановлен классификатор Claude, исправлен протокол train/calibration/test 90/30/30 компаний. Финальные веса сохранены. Holdout 50 148 операций: ~99.9% на слабых метках; regression novel 280: 97.9% модель/Hybrid, 93.6% старая Chain. Не независимая точность. Отдельный template audit: 209 отложенных нормализованных шаблонов, 18 168 операций, ~99.9% — те же слабые синтетические метки.
- gRPC validation, metadata, scope, opt-in Hybrid/manual labels, реальные Go↔Python и Docker smoke tests. После последующих изменений потребуется финальный rebuild/check.
- 141 Python tests + полный Go race/vet прошли на предыдущем checkpoint; добавлены новые проверки auto после этого, они выполняются.
- Development CV: 120 компаний, 320 origins; audit 30 компаний с 2026-07-01 до сих пор НЕ открыт.
- Исправлены календарное обнуление и калибровка: одна временная граница, отдельные calibration-компании, одинаковое применение маски в fit/serve.
- На short14 общий уровень GBM вместо чистого naive улучшил business path WAPE ~0.48→0.33 у ансамбля и coverage ~0.47→0.71; включено для >=14 дней, остаётся low_confidence. Short28 coverage ~0.81. Вес ансамбля оставлен 50/50; поиск .25/.75/.9 не дал однозначного улучшения всех целей.
- Скачан NN5 v3 (287708 байт, MD5 2529489455b2d9f730fbb3c65d39df88), CC BY 4.0, метаданные/сырые файлы в `ml/data/external/nn5`. Внешняя проверка выдачи ATM выявила сдвиг домена и лишний приток у GBM. Исходный отчёт `ml/reports/external_nn5.*` сохранён. После просмотра NN5 добавлена auto-policy: single-channel/nonworkday history → naive, явное предупреждение/low_confidence. Последующая NN5-проверка должна называться regression after adaptation, не независимая.
- Документы: `docs/ML_INTEGRATION.md`, обновлённые ML README/отчёты; runtime зависимости Docker зафиксированы.

### Текущие длительные процессы

- `final_development` (session 71119): CV3, 600 путей, naive/GBM/ensemble/auto, standard + short14/28/56 + gap14 + missing30%. Код ML зафиксирован для этого прогона; не менять его до завершения, чтобы source_changed_during_run был false.
- `final_train` (session 48908): финальный GBM на всех компаниях → `ml/artifacts/gbm_global`, с новой nested calibration.
- Ранее завершены: night_stress, night_ensemble_search, night_short_global, night_nested_calibration, classifier train v2 и template audit. Их результаты в игнорируемом `ml/data`, ключевые отчёты в `ml/reports`.

### Далее

1. Проверить final development, не настраивать модели на audit. Запустить audit один раз с frozen recipe, `--paths 600 --models seasonal_naive,gbm_global,ensemble,auto --protocol audit --out data/final_audit.parquet`. Сгенерировать `reports/quality.md` из audit и `reports/development_stress.md` из final development. Скопировать компактные summary/metadata/segments/calibration в reports для хранения в Git.
2. Новые production artifacts: локальный server restart, живой Go check, Docker rebuild (старый контейнер/образ не содержит последних правок). Проверить конкурирующие запросы, отмену, крупные батчи, ошибки контракта и память на серии запросов.
3. NN5 после auto adaptation писать в отдельный `external_nn5_regression.md`; сохранить исходный отчёт. Не обучать на NN5 и не выдавать ATM за МСП.
4. Завершить data/research report, freeze/reproducibility metadata, scoped commits без Co-Authored-By. Не добавлять `.claude/` и `case/`; не трогать HTTP/другой backend.
5. До 07:00 продолжать ML QA/robustness/ML backend; не обещать безошибочность. По дедлайну остановить новые задачи, оформить результат, отключить heartbeat.

### Ресурсы для уборки

- Локальный ML сервер старой версии: exec session 25949, 127.0.0.1:50071.
- Наш Docker container `zavozik-ml-night-check`, порт127.0.0.1:50072, образ `zavozik-ml:night-20261024`.
- Colima до работы был выключен; запущен default (cpu2/memory4; прежняя конфигурация cpu4/memory6). В конце остановить созданные сервисы; вернуть прежнюю конфигурацию Colima и выключенное состояние, если больше никому не нужны.
- Heartbeat `ml-07-00` активен до04:00UTC. Не создавать дубликат.

## Контрольная точка 04:00 МСК

- Commit `d473711` в ветке ml: основная реализация и артефакты; без coauthor.
- Final development завершён, код не менялся: source 445bc456d1c6…, 320 origins/107 companies.
- Audit завершён ОДИН раз, frozen source ecf8c0e8bab3…, 86 origins/30 companies, 600 paths. Auto business path WAPE 0.28799 vs naive 0.32294, business WAPE30 0.4434, coverage0.8597; 9 business events (5 opening-negative, 4 new), 37 alerts/28 false, precision0.2432, recall1.0, dateMAE4.78days, shortfallMAE1.59m. Не тюнить по audit, не выдавать 9 событий за уверенную гарантию. `reports/quality.md` теперь audit; компактные CSV/metadata в reports/metrics.
- Все153 Python tests прошли; Go race/vet и ML contract tests проходят. После этого изменён только Go fallback metadata/clone/invalid-argument handling; его targeted race/vet прошли. Новый полный прогон нужен при последующих релевантных изменениях.
- Docker заново собран с runtime lock и validation bounds; real Go check PASS. Docker stress:120 concurrent forecasts,8 workers,p95~0.196s,5000 classifications, invalid limits/cancel recovery PASS; отчёт `reports/metrics/docker_concurrency.json`. Локальный server session68636 всё ещё source445; Docker server sourceecf — последний.
- Проверка охвата сохранила `reports/metrics/company_coverage.csv`:13 компаний внеосновногоокна (7ранозавершившихся,6поздноначатых). Запущен дополнительный causal/unseen cohort, файл experiments/excluded_cohort.py; исключает эти13 И audit30 изfit, результаты не смешиваются сaudit.
- Дополнительное исследование до07: Chronos-T5 Tiny. Окружение ml/data/chronos_venv установлено отдельно, chronos-forecasting2.3.2; Apache2.0 model revision29d808298f1a62493e7b9a5e08529d0d930fa189. Исследование только development, не трогать выбранный релиз/audit по результатам; не обещать замену до проверки. Modelweights ещё не загружены на эту отметку.
- Новые скрипты вне production package: ml/experiments/service_stress.py и excluded_cohort.py. Дополнительные изменения/отчёты послеd473711 пока не закоммичены.

## Контрольная точка 04:12 МСК

- Commit 60769fd содержит frozen audit, Docker concurrency и serving bounds. Python forecast recipe остаётся ecf8c0e8bab3; audit не повторять и не тюнить по нему.
- Дополнительный unseen cohort завершён: 13 компаний, 54 origins, auto path WAPE 0.4505 vs naive 0.4728, coverage 0.8086, gap precision 0.5769/recall 0.8824. Все 150 компаний теперь покрыты хотя бы одной проверкой, но отчёты не объединяются. Реально короткие истории слабее: 11 origins, WAPE 1.14, coverage 0.706. Отчёт supplemental_cohort.md.
- Company bootstrap основного audit: снижение auto WAPE 3.49 п.п., 95%-интервал 0.63–5.83 п.п. Это условная оценка на синтетических компаниях, не гарантия переноса.
- Chronos полный development-only прогон запущен 04:04:41, PID 95893, лог ml/data/chronos_development.log. 320 origins × standard/short14/short28 × 600 paths. Checkpoint каждые 10 origins; CPU ~2.25 s/request, ориентировочно 35–45 минут. Не запускать дубликат. Model revision 29d808298f1a62493e7b9a5e08529d0d930fa189, isolated venv ml/data/chronos_venv. Только signed net flow, нельзя выдавать его за gross inflow/outflow. Скрипт не подключён к serving.
- Go fallback дополнительно исправлен: единая validation до ML/fallback, отказ на полностью отсутствующую и недавнюю неизвестную историю, отмена контекста, metadata, неизвестный weekday не равен zero. Assembler проверяет AsOf и даты путей. Живой Docker mlcheck теперь включает полный путь ML -> баланс -> риск и отказ сервиса. Всё PASS, полный go test -race ./... и go vet ./... прошли.
- Исследование слабой разметки классификатора: teacher_labels строит карту пустого назначения на всех компаниях до split; обнаружены 2 train-строки и 2 test-строки, меняющие метку при вычислении карты отдельно внутри partition. Нужно изолировать построение этих меток по partition и перевыпустить честный classifier report. Это не меняет forecast labels/export/recipe. Общая уверенность на неопределённом «Оплата по договору» банку тоже не является надёжной; не обещать безошибочность.

## Контрольная точка 04:28 МСК

- Go degraded-path changes committed 91849b8; full Go race/vet and live Docker mlcheck PASS. All tests still run against existing production classifier until candidate promotion.
- Fixed classifier preparation in code: teacher_label_partitions isolates counterparty-derived weak labels before train/cal/test. Added a regression test proving no cross-partition label leakage.
- Isolated repeat at ml/data/classifier_partition_labels: holdout accuracy .99882348, 9 confident errors, novel .978571; temperature unchanged .643383721. Previous report/weights remain available.
- Missing-counterparty robustness exposed a training shortcut. Fixed-recipe candidate adds 25% dropout views only when purpose is nonempty. Candidate holdout .99874372 (4 extra errors / 50148, 11 confident errors), novel unchanged .978571. Nonempty-purpose/no-counterparty regression improves .893701 -> .944882; confident non-other errors 4 -> 2. No independent external claim. Core train.py now supports name_dropout (default .25), CLI --name-dropout, dev temperature sees same augmentation. 37 classifier tests PASS.
- Further candidate checks RUNNING: template audit session47987 (PID97525), ml/data/classifier_template_v2.log; final all-company candidate session45990 (PID97603), ml/data/classifier_candidate_final.log. Writes ignored candidate artifact, not production yet. IMPORTANT: finalize script was started with SimpleNamespace missing min_confidence for report; fixed in file but running process may fail AFTER saving weights. If so, reconstruct report from evaluation JSON + saved candidate, do not retrain needlessly.
- Tiny Chronos PID95893 still running (~190/320 origins); its script captures whole-package source only at end. Since classifier training and report plotting changed during the run, add honest start/end provenance after completion. Original start source ecf8c0e8bab3. ml/data/chronos_forecast_source.json captures unchanged forecast files; serving forecast algorithms/weights/input data were not edited.
- Larger Chronos-T5 Small downloaded (Apache2; revision a971ba21945c4f1796b17a91fe69214b5f4ad472). Session11344 waits for Tiny to finish then automatically runs experiments/chronos_small_shadow.py, standard only, 200 paths, same net target. Do not start duplicate. Log ml/data/chronos_small_development.log. Small model is NOT in serving.
- WAPE plots fixed to include auto and avoid clipped labels; images regenerated only, frozen forecast metrics unchanged. Report plot visually checked.
- Development threshold diagnostic (no policy change): threshold .1 -> 145 alerts/98 false/recall .959; .5 -> 50 alerts/20 false/recall .612. CSV reports/metrics/development_risk_thresholds.csv.
- Stricter calendar diagnostic computed without new fitting: v1 separates origin dates; 107/320 development horizons cross July1. Filtering to entire target strictly before July1 leaves 213 origins/107companies. Auto WAPE .27724 vs naive .31062, coverage .8521; report metrics/purged_development.*. This is post-hoc diagnostics, not a new audit. Consider adding explicit target-boundary option for future development runs, preserving v1/audit results and no tuning from audit.

## Контрольная точка 04:36 МСК

- Candidate classifier принят: полный fit с dropout .25, веса в artifacts/classifier заменены; старые веса сохранены в ignored data/classifier_release_v1. Template repeat сохранил accuracy .999009, 18 confident errors; no parameter search. Final novel 97.8571%; missing-counterparty + nonempty-purpose 95.2756% vs old final 87.4016%. Case-level error/robustness CSV и compact evaluation JSON сохранены в reports/metrics. 155 Python tests PASS.
- Исправление генерации candidate report после fit выполнено отдельно: ошибка min_confidence была только в report SimpleNamespace; веса не переобучались повторно. classifier.md / classifier_templates.md обновлены.
- Новый Docker classifier version classifier-v1-dac291770bf320c9; live Go check PASS. Python snapshot в образе code-ee49e0e8874d. После сборки менялись только комментарии/CLI/report text (полный source fingerprint меняется и от таких правок); финальный rebuild нужен при следующем реальном изменении Python/артефактов.
- Границы live сервиса: 5000 разных операций, 1 633 890 символов, 6.44с; forecast 5000×200 (1 млн ячеек), 0.29с, ответ16.06МБ; следующий запрос успешен. Не production SLA. reports/metrics/service_limits.json.
- Go Recompute дополнительно отвергает NaN/Inf/отрицательные потоки/переполнение остатка, не заменяя предыдущие корректные Balances при ошибке. Targeted forecast/risk/scenarios race + vet PASS. Остальной backend не трогался.
- Старый локальный Python server PID93186 (session68636, port50071) остановлен SIGTERM. Только наш Docker container zavozik-ml-night-check (новый ID93012e0a...) на50072 остаётся для проверок. Colima cleanup в конце всё ещё нужен.
- Нейросетевые исследования продолжаются: Tiny PID95893 ~260/320, Small автоматически стартует после Tiny в session11344. Не менять serving forecast recipe по audit. Следующий этап: дождаться обоих результатов, оформить честное сравнение/отказ от неподходящих моделей, проверить provenance (изменения касались classifier/report, не расчёта прогноза). Пригодность Tiny по первым origins невысокая; не выдавать нейросеть за улучшение заранее.
- До07:00 ещё можно закрепить строгую границу целевых дат для будущих development-прогонов (отдельная версия split, сохранить v1), подготовить инструмент независимой ручной проверки сомнительных категорий. Не создавать новый внешний «gold test» из уже изученных данных. Зафиксировать финальные результаты/проверки/чистый Git, к дедлайну остановить свои сервисы и heartbeat.

## Контрольная точка 04:49 МСК

- Commit 820deff: classifier isolation/dropout, final weights, reports, supplemental cohort/bootstrap/threshold checks, Go finite balance checks, research scripts. Рабочее дерево содержит только новые research reports/scripts этого этапа + исходные untracked .claude/case.
- Tiny Chronos ЗАВЕРШЁН: 320 origins × 3 scenarios ×600paths, 2197с. Standard WAPE .295355 vs auto .294141; coverage .2651 vs .8695. Short14 WAPE .28948 vs auto .35402, но coverage .2461. Raw Tiny для риска не подходит. Метаданные честно дополнены исходным package hash ecf8..., source_changed_during_run=true и доказанным forecast_code_unchanged=true (сравнены хеши forecast/calendar/data/backtest файлов из chronos_forecast_source.json). Менялись classifier training/report, расчёт прогноза не менялся.
- Small автоматически запустился: PID97384, session11344, лог ml/data/chronos_small_development.log. 320 standard origins, 200paths, среднее ~2.8с/request; ожидать завершение около05:00. Не запускать дубликат. Wrapper теперь сам записывает start/end source fingerprint. Ни Tiny, ни Small не в serving.
- Causal calibration experiment завершён: experiments/chronos_calibration.py, только другие company folds, не более одного последнего завершённого 30-дневного блока ошибки от каждой calibration-компании, минимум20. Доступны205origins (сравнение всех моделей на тех же205). Short14: calibrated Tiny WAPE .29266 vs auto .35143; coverage .7460 vs .7098; recall .8966 vs .8621, precision .2549 vs .2778. На standard однозначного выигрыша нет; calibrated coverage .7691 vs auto .8789, precision хуже. Исследование net-flow, не gross in/out; не переключать production автоматически. Source/result hashes, counts и даты calibration в reports/metrics/chronos_calibration.*.
- experiments/chronos_report.py формирует reports/chronos_shadow.md и metrics/chronos_comparison.* только по полностью завершённым320origin прогонам. После Small запустить его ещё раз (не переобучать). Сейчас отчёт явно помечает Small pending.
- Heartbeat ml-07-00 обновлён, ACTIVE, тот же интервал30мин и дедлайн07:00; читает этот worklog, не повторяет старую работу и обязан закончить cleanup/отчёт. Не создавать новый heartbeat.
- Оставшиеся разумные задачи: оформить результат Small; закрепить строгую target-date границу для будущей разработки отдельным split_v2 без подмены frozen audit; при необходимости подготовить инструмент ручной независимой проверки слабых категорий. Для дальнейшего исследования коротких историй полезнее проверить реальные короткие компании supplemental cohort, чем тюнить на старом audit; калибровка обязана быть доступна по времени, нельзя применять ошибки2026г к прогнозам2025г. Все изменения только ML/связанный Go. До7 сохранять осмысленную работу; в конце cleanup Colima/наших сервисов и выключить heartbeat.

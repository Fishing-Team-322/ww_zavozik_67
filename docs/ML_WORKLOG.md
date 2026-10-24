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

"""Summarize completed shadow runs without fitting or choosing serving models."""
from pathlib import Path
import json
import pandas as pd
from zavozik_ml.eval.report import metric_table
root=Path(__file__).resolve().parents[1]
base=pd.read_csv(root/'data/final_development.summary.csv')
tables=[base[(base.companies=='all')&base.model.isin(['auto','seasonal_naive'])&base.scenario.isin(['standard','short_14','short_28'])]]
metas=[]
pending=[]
for prefix,name in [('chronos_development','chronos_tiny'),('chronos_small_development','chronos_small')]:
    path=root/'data'/f'{prefix}.metadata.json'
    if not path.exists():
        pending.append(name)
        continue
    meta=json.loads(path.read_text())
    assert meta['protocol']=='development_only_shadow'
    # Compare only completed full runs, never the first N companies of a smoke.
    assert meta['origins']==320, f'{prefix}: not a complete run'
    table=pd.read_csv(path.with_name(prefix+'.summary.csv'))
    tables.append(table[(table.companies=='all')&(table.model==name)])
    metas.append(meta)
summary=pd.concat(tables,ignore_index=True).sort_values(['scenario','model'])
out=root/'reports/chronos_shadow.md'
summary.to_csv(root/'reports/metrics/chronos_comparison.csv',index=False)
(root/'reports/metrics/chronos_comparison.metadata.json').write_text(json.dumps({'models':metas,'pending':pending,
    'serving_model_changed':False,'protocol':'development_v1_origins_only','limitation':'No new independent audit. Foundation-model pretraining may include public datasets; this experiment is not an external NN5 test.'},indent=2))
cols={'scenario':'Сценарий','model':'Модель','runs':'N','business_path_wape':'Path WAPE','biz_coverage':'Покрытие','biz_pinball':'Pinball','gap_precision':'Precision','gap_recall':'Recall','gap_brier':'Brier'}
lines=['# Локальное сравнение Chronos с текущим прогнозом','',
    '320 development-точек, 107 компаний, горизонт 30 дней. Audit-компании исключены; даты старта до 2026-07-01. '
    'Это уже исследованный синтетический набор. Модели не дообучались на кейсе; применена та же маска календаря по доступной истории.','',
    metric_table(summary,cols),'',
    'Path WAPE и pinball должны уменьшаться; целевое покрытие p10–p90 около 0.80. '
    'Малое покрытие означает слишком узкую неопределённость, даже если медиана иногда близка к факту.','',
    'Текущий auto и Tiny используют 600 путей, Small — 200 для ограничения памяти. '
    'Это влияет на Monte Carlo точность оценки квантилей и риска. '
    'Все варианты Chronos моделируют чистый бизнес-поток; положительная/отрицательная части не являются валовыми поступлениями и списаниями. '
    'Поэтому существующий контракт gRPC ими автоматически не заменён.','',
    'Скачаны публичные веса Small/Tiny; сами выписки обрабатывались локально. '
    'Лицензия моделей Apache 2.0; источники: [Tiny](https://huggingface.co/amazon/chronos-t5-tiny), '
    '[Small](https://huggingface.co/amazon/chronos-t5-small), [реализация](https://github.com/amazon-science/chronos-forecasting).','',
    '## Время и воспроизводимость','']
for m in metas:
    lines.append(f"- `{m['model']}`, revision `{m['revision']}`: {m['paths']} путей, "
        f"p50 {m['p50_request_seconds']:.2f} с, p95 {m['p95_request_seconds']:.2f} с на локальном CPU. "
        f"SHA256 весов `{m['weights_sha256']}`.")
cal_path=root/'data/chronos_calibration.summary.csv'
if cal_path.exists():
    calibrated=pd.read_csv(cal_path)
    calibrated=calibrated[calibrated.companies=='all']
    lines+=['','## Калибровка по завершённым прогнозам других компаний','',
        'Дополнительный development-эксперимент: 3 группы компаний. Для каждой точки берётся по одному последнему '
        '30-дневному блоку ошибки из компаний других групп, причём весь факт уже известен на дату прогноза. '
        'Нужно минимум 20 таких компаний; поэтому осталось 205 точек, и все модели ниже сравниваются только на них. '
        'Ошибки нормируются на исторический масштаб потоков. Медиана блока вычитается; bootstrap создаёт целые '
        'траектории ошибки, а не независимые интервалы отдельных дней.','',metric_table(calibrated,cols),'',
        'На короткой истории это улучшает медиану и неопределённость относительно auto на том же подмножестве, '
        'но покрытие всё ещё ниже 80%, ложные сигналы остаются, а общая история не даёт однозначной замены. '
        'Калибровка исследована после просмотра Tiny development; новый независимый audit не проводился. '
        'Артефакт не подключён к production.']
if pending:lines+=['','Ещё выполняется: '+', '.join(pending)+'. Не сравнивать неполный checkpoint с полным набором.']
lines+=['','Команды и отдельное окружение описаны в `ml/experiments/README.md`. '
    'Метаданные и полные численные сравнения сохранены рядом в `metrics/chronos_comparison.*`. '
    'Настройки production-прогноза по результатам audit не менялись.']
out.write_text('\n'.join(lines)+'\n')
print(summary[list(cols)].to_string(index=False))

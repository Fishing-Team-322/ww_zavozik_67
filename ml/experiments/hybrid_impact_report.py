"""Summarize real Go Hybrid input drift without fitting or scoring correctness."""
from collections import Counter
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root/'data/hybrid_flow_impact.json'
report = json.loads(source.read_text())
assert not set(report['companies']) & set(report['excluded_companies'])
keys = ['operations', 'category_changed', 'internal_membership_changed',
        'changed_category_turnover', 'changed_internal_membership_turnover', 'business_net_delta']
totals = {key: sum(row[key] for row in report['companies'].values()) for key in keys}
transitions = Counter()
for row in report['companies'].values():
    transitions.update(row['transitions'])
report.update(totals=totals,
    affected_companies=sum(row['category_changed']>0 for row in report['companies'].values()),
    flow_affected_companies=sum(row['internal_membership_changed']>0 for row in report['companies'].values()),
    source_report_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    diagnostic_go_source_sha256=hashlib.sha256((root.parent/'backend/cmd/mlimpact/main.go').read_bytes()).hexdigest())
(root/'reports/metrics/hybrid_flow_impact.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
lines = ['# Влияние Go Hybrid на вход прогнозной модели', '',
    f"Реальный Go Hybrid → локальный Python gRPC, модель `{report['model_version']}`, порог 0.8. "
    f"{len(report['companies'])} development-компаний, только операции до {report['before_exclusive']} "
    '(дата исключена), audit-компании исключены. Парсинг/дедупликация и исходные правила — те же, что в export. '
    'Ни forecast fit/audit, ни production export не изменены.', '',
    '| Показатель | Значение |', '|---|---:|',
    f"| Операций после дедупликации | {totals['operations']:,} |",
    f"| Сменили категорию | {totals['category_changed']:,} ({100*totals['category_changed']/totals['operations']:.2f}%) |",
    f"| Сменили включение в бизнес-поток | {totals['internal_membership_changed']:,} |",
    f"| Компаний со сменой включения операций | {report['flow_affected_companies']} |",
    f"| Сумма операций со сменой включения, ₽ | {totals['changed_internal_membership_turnover']:,.2f} |",
    f"| Разница суммарного business net (Hybrid − rules), ₽ | {totals['business_net_delta']:,.2f} |", '',
    'Это изменение определения потока, **не экономия, не ошибка прогноза и не доказательство правильности ML-категории**. '
    'Суммы относятся ко всему выбранному периоду/набору синтетических компаний. '
    'Наблюдаемый банковский остаток не изменяется при смене категории.', '',
    '| Переход | Операций |', '|---|---:|']
lines += [f'| {key} | {count:,} |' for key, count in transitions.most_common()]
lines += ['', 'Большинство новых меток уточняет `other`, но 402 перехода `other → own_transfer`, '
    '22 `other → owner_loan` и 5 `utilities → own_transfer` меняют исключение внутренних движений. '
    'Даже переходы supplier/services/loan_payment, не меняющие общий поток, меняют признаки категорий.', '',
    'Перед включением Hybrid: согласовать спорные внутренние операции по документам; '
    'зафиксировать версию политики категоризации; пересобрать отдельный development export; '
    'проверить forecast на split_v2 с причинной калибровкой и тем же upstream на обучении/сервинге. '
    'Frozen audit не использовать для выбора этой новой политики. '
    'Текущие production GBM/auto и исходный flows.csv оставлены без изменений.', '',
    'Веса классификатора уже обучены на кейсе. Эта диагностика измеряет только сдвиг входа '
    'при подключении, а не обобщение на неизвестные операции. '
    'FailOpen выключен: недоступность ML завершает команду ошибкой, а не нулевым сдвигом.']
(root/'reports/hybrid_flow_impact.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(totals))

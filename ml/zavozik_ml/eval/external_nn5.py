"""External domain-shift check on licensed NN5 ATM withdrawal series.

No cash-balance or insolvency claims: NN5 contains withdrawals, not company
account balances. No fitting or tuning on the external test tails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from zavozik_ml import forecasters
from zavozik_ml.forecasters import models  # noqa: F401
from zavozik_ml.forecasters.base import History
from zavozik_ml.forecasters.base import select_model
from zavozik_ml.provenance import source_fingerprint
from zavozik_ml.serving.server import load_artifacts, model_version

ROOT = Path(__file__).resolve().parents[2]


def read_nn5(path):
    for line in path.read_text().splitlines():
        if not line or line.startswith(('#', '@')):
            continue
        name, start, raw = line.split(':', 2)
        day = datetime.strptime(start, '%Y-%m-%d %H-%M-%S').date()
        values = np.array([np.nan if v == '?' else float(v) for v in raw.split(',')])
        yield name, day, values


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, default=ROOT/'data/external/nn5/nn5_daily_dataset_with_missing_values.tsf')
    p.add_argument('--artifacts', type=Path, default=ROOT/'artifacts')
    p.add_argument('--out', type=Path, default=ROOT/'reports/external_nn5.md')
    args = p.parse_args()
    load_artifacts(args.artifacts)
    names = ['seasonal_naive', 'ets', 'gbm_global', 'ensemble', 'auto']
    results = []
    for name, start, values in read_nn5(args.data):
        # Two disjoint 30-day windows at the end; all missing target days excluded.
        for tail in (30, 60):
            n = len(values)-tail
            raw = values[:n]
            h = History([start+timedelta(days=i) for i in range(n)], np.zeros(n),
                        np.nan_to_num(raw), np.isnan(raw))
            actual = values[n:n+30]
            valid = np.isfinite(actual)
            if not valid.any():
                continue
            for model in names:
                paths = select_model(model, h).forecast(h,30,400,np.random.default_rng(20261024))
                pred = np.quantile(paths.outflow,[.1,.5,.9],axis=0)
                y, median = actual[valid],pred[1,valid]
                denom = np.abs(y)+np.abs(median)
                results.append(dict(series=name, tail=tail, model=model, days=int(valid.sum()),
                    abs_error=float(np.abs(y-median).sum()), volume=float(np.abs(y).sum()),
                    smape_sum=float(np.divide(2*np.abs(y-median),denom,out=np.zeros_like(y),where=denom>0).sum()),
                    covered=int(((y>=pred[0,valid])&(y<=pred[2,valid])).sum()),
                    invented_inflow=float(np.median(paths.inflow,axis=0)[valid].sum()),
                    low_confidence=paths.low_confidence))
    frame = pd.DataFrame(results)
    aggregate=[]
    for model,g in frame.groupby('model'):
        aggregate.append(dict(model=model,windows=len(g),days=int(g.days.sum()),
            daily_wape=g.abs_error.sum()/g.volume.sum(),smape=g.smape_sum.sum()/g.days.sum(),
            coverage=g.covered.sum()/g.days.sum(),spurious_inflow_ratio=g.invented_inflow.sum()/g.volume.sum()))
    summary=pd.DataFrame(aggregate)
    from .report import metric_table
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.with_suffix('.csv').write_text(summary.to_csv(index=False))
    meta=dict(data_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),source_sha256=source_fingerprint(),
              model_versions={m:model_version(m) for m in names},target='daily ATM withdrawals, not account balance',
              fit_external=False,paths=400,seed=20261024,windows='last two disjoint 30-day windows per series')
    args.out.with_suffix('.json').write_text(json.dumps(meta,indent=2))
    table=metric_table(summary,{'model':'Модель','windows':'Окон','days':'Дней','daily_wape':'Daily WAPE',
        'smape':'sMAPE','coverage':'p10–p90 coverage','spurious_inflow_ratio':'Лишний приток / факт оттока'})
    args.out.write_text(f'''# Внешняя проверка: NN5

Источник: [NN5 Daily Dataset, version 3](https://zenodo.org/records/4656110),
Godahewa, Bergmeir, Webb, Hyndman, Montero-Manso; лицензия CC BY 4.0
([метаданные лицензии](https://zenodo.org/api/records/4656110)).
111 ежедневных рядов выдачи наличных банкоматами Великобритании. Архив проверен по MD5 издателя;
данные хранятся локально в игнорируемом `ml/data/external/nn5`, не включаются в продукт.

Это проверка **сдвига источника**, а не качества бизнес-разрывов. Исходные значения остаются
в единицах NN5. История используется только до точки прогноза, пропуски помечены, а неизвестный
будущий факт исключён из метрик. На каждом ряду две непересекающиеся последние 30-дневные
проверки; модели не обучаются на NN5. Выходные с фактической активностью не обнуляются.
Глобальная модель обучена на синтетических российских компаниях; её перенос на банкоматы
не был целью обучения. Нельзя подменять этими числами оценку российского МСП.

{table}

Метрики относятся к ежедневному **оттоку**, не к остатку. 0.25 означает 25%.
Последний столбец выявляет положительный приток, придуманный моделью для ряда только с выдачами.
В NN5 нет остатков, входящих платежей, назначений, категорий или событий разрыва —
поэтому вероятность/дату/сумму банкротства на этих данных не оцениваем.

Настройки, хеши данных и версии моделей сохранены в `{args.out.with_suffix('.json').name}`.
''')
    print(table)

if __name__=='__main__':
    main()

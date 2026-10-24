"""Research check on genuinely young/early-ended supplemental companies.

Uses the fixed Tiny recipe, not the locked audit. Residual calibration comes
only from other development companies and fully completed pre-July targets.
Never backfills a 2025 forecast with 2026 errors. No production model changes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

# Match the working shadow runner's runtime import order on macOS: initialize
# Torch before LightGBM/OpenMP (loaded by backtest). Both load native runtimes.
# Tests import only the pure selection helper and do not need the Torch extra.
if __name__ == '__main__':
    import torch
    from chronos_shadow import ChronosNet, flat_results, MODEL, REVISION

import numpy as np
import pandas as pd

from zavozik_ml.data import DEFAULT_FLOWS, load_companies
from zavozik_ml.eval.backtest import Config, Origin, evaluate_origin, stress_history, _metrics, _first_day_below
from zavozik_ml.eval.report import metric_table
from zavozik_ml.provenance import source_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def unpack(frame):
    records = []
    for _, group in frame.groupby(['model', 'company_id', 'as_of', 'scenario']):
        group = group.sort_values('h')
        if group.h.tolist() != list(range(1, 31)):
            raise ValueError('expected exactly one complete 30-day trajectory')
        row = group.iloc[0].to_dict()
        row.update(actual=group.actual.to_numpy(), adjusted=group.adjusted.to_numpy(),
                   q=np.array([group.p10, group.p50, group.p90]), daily_gap_prob=group.daily_gap_prob.to_numpy())
        records.append(row)
    return records


def available_calibration(records, as_of, scenario, excluded, boundary):
    latest = {}
    for row in sorted(records, key=lambda item: item['as_of']):
        target_end = pd.Timestamp(row['as_of']) + pd.Timedelta(days=30)
        if row['company_id'] in excluded or row['scenario'] != scenario:
            continue
        if target_end <= pd.Timestamp(as_of) and target_end < pd.Timestamp(boundary):
            latest[row['company_id']] = row
    return list(latest.values())


def history_scale(history):
    activity = (history.inflow[-91:] + history.outflow[-91:])[~history.missing[-91:]]
    return float(activity.mean()) + 1 if len(activity) else 1.


def main():
    import torch
    from chronos_shadow import ChronosNet, flat_results, MODEL, REVISION

    source_start = source_fingerprint()
    source = ROOT/'data/supplemental_cohort.parquet'
    calibration_source = ROOT/'data/chronos_development.parquet'
    reference = pd.read_parquet(source)
    references = unpack(reference[reference.model.isin(['auto', 'seasonal_naive'])])
    companies = {company.id: company for company in load_companies()}
    ids = set(reference.company_id)
    spec = json.loads((ROOT/'eval/split_v2.json').read_text())
    assert not ids & set(spec['audit_companies'])
    calibration = unpack(pd.read_parquet(calibration_source))
    assert not set(row['company_id'] for row in calibration) & (ids | set(spec['audit_companies']))
    for row in calibration:
        company = companies[row['company_id']]
        index = company.history.dates.index(pd.Timestamp(row['as_of']).date())
        row['scale'] = history_scale(stress_history(company.history.head(index+1), row['scenario']))

    cfg = Config(n_paths=600)
    torch.set_num_threads(4)
    model = ChronosNet()
    origins = reference[['company_id', 'as_of']].drop_duplicates().sort_values(['as_of', 'company_id'])
    results, calibrated, diagnostics = [], [], []
    started = time.monotonic()
    for i, origin in enumerate(origins.itertuples(index=False), 1):
        company = companies[origin.company_id]
        index = company.history.dates.index(pd.Timestamp(origin.as_of).date())
        seed = int.from_bytes(hashlib.sha256(f'42:chronos_supplemental:{company.id}:{origin.as_of}'.encode()).digest()[:8], 'little')
        row = evaluate_origin(model, Origin(company, index), cfg, np.random.default_rng(seed))
        results.append(row)
        # Fixed before seeing results: use matching 14/28-day residual stresses
        # for actually <=14/28-day histories; otherwise use standard histories.
        scenario = 'short_14' if index+1 <= 14 else 'short_28' if index+1 <= 28 else 'standard'
        candidates = available_calibration(calibration, origin.as_of, scenario, ids | set(spec['audit_companies']), spec['audit_start'])
        diagnostic = dict(company_id=company.id, as_of=origin.as_of, history_days=index+1,
                          residual_scenario=scenario, calibration_companies=len(candidates), calibrated=False)
        if len(candidates) >= 20:
            residual = np.array([(p['adjusted']-p['q'][1])/p['scale'] for p in candidates])
            residual -= np.median(residual, axis=0)
            rng = np.random.default_rng(seed+1)
            balances = row['q'][1] + residual[rng.integers(len(residual), size=cfg.n_paths)] * history_scale(company.history.head(index+1))
            quantiles = np.quantile(balances, [.1, .5, .9], axis=0)
            pred = _first_day_below(balances, cfg.gap_threshold)
            calibrated.append(dict(row, model='chronos_tiny_residual_calibrated', q=quantiles,
                daily_gap_prob=(balances<0).mean(axis=0), gap_prob=float((balances.min(axis=1)<0).mean()),
                gap_alarm=pred is not None, pred_gap_day=pred, pred_shortfall=max(0., -float(quantiles[1].min())),
                mae_run=float(np.abs(row['actual']-quantiles[1]).mean()), low_confidence=True))
            diagnostic.update(calibrated=True, latest_calibration_target=str(max(pd.Timestamp(p['as_of'])+pd.Timedelta(days=30) for p in candidates).date()))
        diagnostics.append(diagnostic)
        if i % 10 == 0:
            print(f'{i}/{len(origins)} origins, elapsed {time.monotonic()-started:.1f}s', flush=True)

    keys = {(row['company_id'], row['as_of']) for row in calibrated}
    compared = results + references
    tables = []
    for cohort, rows in [('all_supplemental', compared), ('calibration_available',
            [row for row in compared if (row['company_id'], row['as_of']) in keys]+calibrated)]:
        frame = pd.DataFrame(rows)
        if frame.empty:
            continue
        for segment, subset in [('all', frame), ('actual_short_under_90d', frame[frame.history_days<90])]:
            for name, group in subset.groupby('model'):
                tables.append(dict(cohort=cohort, segment=segment, model=name, **_metrics(group, cfg)))
    summary = pd.DataFrame(tables)
    out = ROOT/'data/chronos_supplemental'
    flat_results(results+calibrated, cfg).to_parquet(out.with_suffix('.parquet'), index=False)
    metrics = ROOT/'reports/metrics/chronos_supplemental'
    summary.to_csv(metrics.with_suffix('.summary.csv'), index=False)
    pd.DataFrame(diagnostics).to_csv(metrics.with_suffix('.origins.csv'), index=False)
    meta = dict(protocol='supplemental_research_no_model_selection', model=MODEL, revision=REVISION,
        origins=len(origins), companies=len(ids), calibration_available_origins=len(keys),
        minimum_calibration_companies=20, target_end_exclusive=spec['audit_start'], paths=600,
        source_sha256_at_start=source_start, source_changed_during_run=source_start!=source_fingerprint(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        flows_sha256=hashlib.sha256(DEFAULT_FLOWS.read_bytes()).hexdigest(),
        baseline_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        calibration_predictions_sha256=hashlib.sha256(calibration_source.read_bytes()).hexdigest(),
        seconds=time.monotonic()-started, serving_model_changed=False,
        limitation='Previously inspected synthetic supplemental cohort. Few actually young companies. '
                   'Net flow only; no independent external audit and no pooling with locked audit.')
    metrics.with_suffix('.metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
    columns = {'cohort':'Когорта', 'segment':'Сегмент', 'model':'Модель', 'runs':'N',
        'business_path_wape':'Path WAPE', 'biz_coverage':'Покрытие', 'biz_pinball':'Pinball',
        'gap_precision':'Precision', 'gap_recall':'Recall'}
    (ROOT/'reports/chronos_supplemental.md').write_text(
        '# Chronos на реально коротких и рано завершённых историях\n\n'
        'Фиксированный Tiny, 600 путей, 54 точки 13 дополнительных компаний. '
        'Модели Go/GBM не переобучались: сравнение с сохранённым supplemental-прогоном. '
        'Калибровка использует только другие development-компании, по одному последнему завершённому '
        '30-дневному блоку на компанию; весь факт строго до 2026-07-01 и доступен на дату прогноза. '
        'Для истории до 14/28 дней взяты соответствующие stress-остатки, иначе standard; минимум 20 компаний.\n\n'
        +metric_table(summary, columns)+'\n\n'
        'Строки calibration_available сравнивают модели на одинаковых точках. Для ранних историй '
        'нет доступных calibration-блоков: ошибки 2026 года не перенесены в 2025 год. '
        'Это малый уже изученный синтетический набор, не новый audit. Прогнозирует чистый поток, '
        'не валовые поступления/списания. Изменений serving нет.\n')
    print(summary[list(columns)].to_string(index=False), flush=True)


if __name__ == '__main__':
    main()

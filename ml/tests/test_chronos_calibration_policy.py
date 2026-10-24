import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('chronos_supplemental',
    Path(__file__).parents[1]/'experiments/chronos_supplemental.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_calibration_never_borrows_future_same_company_or_boundary_targets():
    rows = [dict(company_id=cid, as_of=day, scenario=scenario) for cid, day, scenario in [
        ('A', '2026-04-01', 'standard'), ('A', '2026-05-01', 'standard'),
        ('B', '2026-05-02', 'standard'), ('C', '2026-06-01', 'standard'),
        ('SELF', '2026-04-01', 'standard'), ('D', '2026-04-01', 'short_14')]]
    selected = module.available_calibration(rows, '2026-05-31', 'standard', {'SELF'}, '2026-07-01')
    assert [(r['company_id'], r['as_of']) for r in selected] == [('A', '2026-05-01')]
    assert not module.available_calibration(rows, '2025-12-31', 'standard', {'SELF'}, '2026-07-01')
    selected = module.available_calibration(rows, '2026-08-31', 'standard', {'SELF'}, '2026-07-01')
    assert {r['company_id'] for r in selected} == {'A', 'B'}

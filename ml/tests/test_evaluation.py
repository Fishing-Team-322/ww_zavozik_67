from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from zavozik_ml.data import Company
from zavozik_ml.forecasters.base import History, Paths
from zavozik_ml.eval.backtest import Config, Origin, evaluate_origin, make_origins, _metrics, calibration_error
from zavozik_ml.eval.backtest import stress_history, summarize


class Fixed:
    name = 'fixed'

    def forecast(self, history, horizon, n_paths, rng):
        return Paths(np.zeros((n_paths, horizon)), np.ones((n_paths, horizon))*20)


def company(n=40):
    return Company('C', History(
        [date(2026, 1, 1)+timedelta(days=i) for i in range(n)],
        np.zeros(n), np.ones(n)*20, np.zeros(n, bool),
    ), 500-np.arange(n)*20.)


def test_account_and_business_targets_separated():
    c=company()
    c.history.categories['owner_loan']=np.zeros(40)
    c.history.categories['owner_loan'][20]=1000
    c.balance[20:]+=1000
    cfg=Config(horizon=30,n_paths=10)
    r=evaluate_origin(Fixed(), Origin(c,9),cfg,np.random.default_rng(1))
    assert r['gap_true'] and not r['account_gap_true']
    assert r['pred_gap_day']==17 and r['gap_day']==17
    assert r['gap_alarm']
    m=_metrics(pd.DataFrame([r]),cfg)
    assert m['gap_date_mae_days']==0
    assert m['gap_shortfall_mae']==0
    assert m['account_gap_precision']==0


def test_daily_alarm_is_not_horizon_probability():
    # Go alarms on per-day probability. Disjoint single-path events can have
    # high horizon probability without any daily probability reaching threshold.
    class Disjoint:
        name='disjoint'
        def forecast(self,history,horizon,n_paths,rng):
            balances=np.full((20,horizon),100.)
            for i in range(10):balances[i,i]=-1
            delta=np.diff(np.column_stack([np.full(20,100.),balances]),axis=1)
            return Paths(np.maximum(delta,0),np.maximum(-delta,0))
    c=company();c.balance[:]=100
    r=evaluate_origin(Disjoint(),Origin(c,9),Config(n_paths=20),np.random.default_rng(1))
    assert r['gap_prob']==.5 and not r['gap_alarm']


def test_incomplete_history_is_evaluated_but_unknown_future_is_not():
    c=company(100);c.history.missing[50]=True
    origins=make_origins(c,Config(origins=1))
    assert len(origins)==1  # old implementation dropped this company
    c.history.missing[90]=True
    assert not make_origins(c,Config(origins=1))


def test_calibration_error_includes_probability_one():
    assert calibration_error(np.array([0.,1.]),np.array([False,True]))==0
    assert calibration_error(np.array([0.,1.]),np.array([True,False]))==1


def test_shared_go_risk_contract():
    import json
    from pathlib import Path
    from zavozik_ml.eval.backtest import _first_day_below
    fixtures=json.loads((Path(__file__).parent/'fixtures/risk_contract.json').read_text())
    for c in fixtures:
        paths=np.array(c['paths'],float)
        day=_first_day_below(paths,.1)
        assert day == (None if c['date_index'] is None else c['date_index']+1),c['name']
        assert (paths.min(axis=1)<0).mean()==pytest.approx(c['probability'])
        if day is not None:
            assert max(0,-np.quantile(paths,.5,axis=0).min())==pytest.approx(c['shortfall'])


def test_stress_preserves_future_and_does_not_modify_source():
    c = company(100)
    h = c.history.head(70)
    short = stress_history(h, 'short_14')
    assert len(short) == 14 and short.dates[-1] == h.dates[-1]
    masked = stress_history(h, 'gap_14')
    assert masked.missing.sum() == 14 and not h.missing.any()
    assert (masked.outflow[masked.missing] == 0).all()
    cfg = Config(n_paths=10)
    a = evaluate_origin(Fixed(), Origin(c, 69), cfg, np.random.default_rng(1))
    b = evaluate_origin(Fixed(), Origin(c, 69), cfg, np.random.default_rng(1), 'short_14')
    np.testing.assert_array_equal(a['actual'], b['actual'])
    report = summarize([a, b], cfg, {'C'})
    assert set(report.scenario) == {'standard', 'short_14'}
    assert (report.runs == 1).all()


def test_protocol_boundary_excludes_the_entire_future_in_v2():
    from zavozik_ml.eval.backtest import protocol_origins
    c = company(240)
    # May 31 + 30 days is June 30; June 1 + 30 days reaches July 1.
    origins = [Origin(c, (d-date(2026, 1, 1)).days) for d in
               (date(2026, 5, 31), date(2026, 6, 1), date(2026, 6, 30), date(2026, 7, 1))]
    spec = {'version': 2, 'audit_start': '2026-07-01', 'audit_companies': ['AUDIT'],
            'development_target_policy': 'all_target_dates_before_audit_start'}
    selected = protocol_origins(origins, Config(horizon=30), 'development', spec)
    assert [o.as_of for o in selected] == [date(2026, 5, 31)]
    # The configured horizon, rather than a hard-coded 30-day gap, controls the purge.
    selected = protocol_origins(origins, Config(horizon=1), 'development', spec)
    assert [o.as_of for o in selected] == [date(2026, 5, 31), date(2026, 6, 1)]
    # Preserve historical v1 reproducibility and the locked audit company/time policy.
    assert len(protocol_origins(origins, Config(), 'development', dict(spec, version=1))) == 3
    from dataclasses import replace
    origins = [replace(o, company=replace(c, id='AUDIT')) for o in origins]
    assert not protocol_origins(origins, Config(), 'development', spec)
    for version in (1, 2):
        selected = protocol_origins(origins, Config(), 'audit', dict(spec, version=version))
        assert [o.as_of for o in selected] == [date(2026, 7, 1)]


def test_protocol_rejects_unsupported_split_semantics():
    from zavozik_ml.eval.backtest import protocol_origins
    spec = {'version': 3, 'audit_start': '2026-07-01', 'audit_companies': []}
    with pytest.raises(ValueError, match='split version'):
        protocol_origins([], Config(), 'development', spec)
    with pytest.raises(ValueError, match='target policy'):
        protocol_origins([], Config(), 'development', dict(spec, version=2))

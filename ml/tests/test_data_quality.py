from datetime import date, timedelta

import numpy as np

from zavozik_ml.forecasters.base import History


def test_missing_flags_are_available_only_after_detection():
    h = History(
        dates=[date(2025, 1, 1) + timedelta(days=i) for i in range(5)],
        inflow=np.ones(5), outflow=np.zeros(5),
        missing=np.array([False, True, True, True, True]),
        missing_known_on=np.array(['NaT', *['2025-01-05'] * 4], dtype='datetime64[D]'),
    )
    assert not h.head(4).missing.any()
    np.testing.assert_array_equal(h.head(5).missing, h.missing)
    assert not h.head(5).head(4).missing.any()
    assert len(h.head(0)) == 0


def test_loader_rejects_malformed_daily_flow(tmp_path):
    import pandas as pd
    import pytest
    from zavozik_ml.data import load_companies
    base = pd.DataFrame(dict(company_id=['C', 'C'], date=['2026-01-01', '2026-01-02'],
                             inflow=[1., 2.], outflow=[0., 0.], balance=[1., 3.], missing=[False, False]))
    path = tmp_path/'flows.csv'
    base.to_csv(path, index=False)
    assert len(load_companies(path)[0].history) == 2
    for column, value in [('date', '2026-01-01'), ('inflow', -1), ('inflow', float('inf')), ('missing', 'unknown')]:
        bad = base.copy()
        bad[column] = bad[column].astype(object)
        bad.loc[1, column] = value
        bad.to_csv(path, index=False)
        with pytest.raises(ValueError):
            load_companies(path)

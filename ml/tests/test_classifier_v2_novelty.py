import numpy as np
import pytest

from zavozik_ml.classify_v2.novelty import fit_reference, ranks


def test_class_conditioned_calibration_handles_different_known_distance_scales():
    # Broad `other` has larger legitimate distances than compact salary. One
    # raw global threshold treats most other as novel and misses salary outliers.
    dist = np.concatenate([np.linspace(.1, .2, 100), np.linspace(.4, .7, 100)])
    pred = np.repeat([0, 1], 100)
    keys = ("salary", "other")
    reference = fit_reference(dist, pred, keys)
    score = ranks(dist, pred, keys, reference)
    assert (score[pred == 0] > .95).mean() <= .05
    assert (score[pred == 1] > .95).mean() <= .05
    # A distance that is exceptional for salary is ordinary for broad other.
    s = ranks(np.array([.3, .5]), np.array([0, 1]), keys, reference)
    assert s[0] > .95 and s[1] < .95


def test_rare_and_new_categories_use_global_fallback_without_unknown_labels():
    dist = np.linspace(.1, .5, 100)
    pred = np.array([0] * 95 + [1] * 5)
    ref = fit_reference(dist, pred, ("known", "rare"))
    assert set(ref["by_category"]) == {"known"}
    s = ranks(np.array([.9, 0]), np.array([1, 2]), ("known", "rare", "new"), ref)
    assert s[0] == 1
    assert 0 <= s[1] < .1


def test_equal_distance_ties_do_not_manufacture_false_novelty():
    d = np.full(100, .2)
    ref = fit_reference(d, np.zeros(100, int), ("known",))
    assert not (ranks(d, np.zeros(100, int), ("known",), ref) > .95).any()
    assert ranks(np.array([.21]), np.array([0]), ("known",), ref)[0] == 1


def test_reference_rejects_invalid_numeric_state():
    with pytest.raises(ValueError):
        fit_reference(np.array([np.nan]), np.array([0]), ("known",))
    with pytest.raises(ValueError):
        fit_reference(np.array([.1]), np.array([1]), ("known",))
    ref = fit_reference(np.linspace(.1, .3, 40), np.zeros(40, int), ("known",))
    ref["global"] = []
    with pytest.raises(ValueError):
        ranks(np.array([.2]), np.array([0]), ("new",), ref)

import copy

from zavozik_ml.classify_v2.report import acceptance


def examples():
    category = dict(n=280, accuracy=.999, macro_f1=.99, ece=.01)
    dataset = dict(category=category, linear_v1=dict(accuracy=.99, macro_f1=.99),
                   channel=dict(accuracy=.97), tags=dict(micro_f1=.95),
                   digital_ruble=dict(n=10, category_correct=10, channel_correct=10, categories_in_taxonomy=True))
    ev = dict(datasets={k: copy.deepcopy(dataset) for k in ("company_test", "novel_regression", "authored_holdout")})
    bench = dict(batch_size=256, distinct_normalized_inputs=256, p95_s=.3)
    nov = dict(hidden_novel_recall=.9, known_false_positive_rate=.03)
    return ev, bench, nov


def test_acceptance_does_not_round_274_of_280_up_to_literal_97_9():
    ev, bench, nov = examples()
    assert acceptance(ev, bench, nov)["all_passed"]
    ev["datasets"]["novel_regression"]["category"]["accuracy"] = 274/280
    assert not acceptance(ev, bench, nov)["gates"]["regression_accuracy_at_least_97_9_percent"]
    ev["datasets"]["novel_regression"]["category"]["accuracy"] = 275/280
    assert acceptance(ev, bench, nov)["gates"]["regression_accuracy_at_least_97_9_percent"]


def test_missing_novelty_or_digital_results_cannot_pass_vacuously():
    ev, bench, nov = examples()
    assert not acceptance(ev, bench, None)["all_passed"]
    ev["datasets"]["authored_holdout"]["digital_ruble"]["n"] = 0
    assert not acceptance(ev, bench, nov)["all_passed"]


def test_benchmark_must_include_256_distinct_inputs_and_within_budget():
    ev, bench, nov = examples()
    bench["distinct_normalized_inputs"] = 1
    assert not acceptance(ev, bench, nov)["all_passed"]
    bench["distinct_normalized_inputs"] = 256
    bench["p95_s"] = 1.01
    assert not acceptance(ev, bench, nov)["all_passed"]


def test_new_holdout_requires_strict_improvement_and_company_delta_is_pp():
    ev, bench, nov = examples()
    c = ev["datasets"]["company_test"]
    c["category"]["accuracy"] = .987  # exactly0.3 percentage points below.99
    assert acceptance(ev, bench, nov)["gates"]["company_accuracy_within_0_3pp"]
    c["category"]["accuracy"] = .9869
    assert not acceptance(ev, bench, nov)["gates"]["company_accuracy_within_0_3pp"]
    ev["datasets"]["authored_holdout"]["category"]["accuracy"] = .99
    assert not acceptance(ev, bench, nov)["gates"]["new_holdout_category_better_than_v1"]

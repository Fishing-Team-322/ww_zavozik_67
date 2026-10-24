import math

import grpc
import numpy as np
import pandas as pd
import pytest
from categorize.v1 import categorizer_pb2 as pb
from categorize.v1 import categorizer_pb2_grpc as pb_grpc

from zavozik_ml.classify import CATEGORIES, DEFAULT_DIR, Classifier, Op
from zavozik_ml.classify import labels
from zavozik_ml.classify.evaluate import NOVEL, load_novel
from zavozik_ml.classify.text import N_FEATURES, counterparty_type, features, normalize
from zavozik_ml.serving.server import build_server


@pytest.fixture(scope="module")
def clf():
    return Classifier.load(DEFAULT_DIR)


def test_categories_match_go_and_openapi():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    domain = (root / "backend/internal/domain/domain.go").read_text(encoding="utf-8")
    api = (root / "api/openapi.yaml").read_text(encoding="utf-8")
    for c in CATEGORIES:
        assert f'"{c}"' in domain
        assert c in api
    assert len(CATEGORIES) == 20 and len(set(CATEGORIES)) == 20


def test_normalize():
    assert normalize("Оплата поставщику цифровыми рублями за товар") == "оплата поставщику за товар"
    assert normalize("Аренда за май, оплата ЦР") == "аренда за мес оплата"
    assert normalize("Перевод на счёт цифрового рубля") == "перевод на счет"
    assert normalize("oплата пo дoгoвору 15") == "оплата по договору 0"  # латинские o
    assert normalize("Оплата по УПД № 12 от 01.02.2026. НДС не облагается") == "оплата по упд номер 0 от дата"
    assert normalize("SberPay") == "sberpay"
    assert normalize("") == "" and normalize(None) == ""


def test_counterparty_type():
    assert counterparty_type("0071234567") == "org"
    assert counterparty_type("001234567890") == "person"
    assert counterparty_type("") == "none"
    assert counterparty_type("12-34") == "bad"


def test_features_in_range():
    idx, val = features(Op("out", "Оплата за товар", "ООО «Ромашка»", "0071234567", 1000))
    assert idx and all(0 <= i < N_FEATURES for i in idx) and all(math.isfinite(v) for v in val)


def test_artifact_small_enough():
    size = sum(p.stat().st_size for p in DEFAULT_DIR.iterdir())
    assert size < 20e6


def _one(clf, *args):
    return clf.predict([Op(*args)])[0]


@pytest.mark.parametrize("direction,purpose,name,inn,want", [
    ("out", "Оплата поставщику цифровыми рублями за товар по счету № 15", "ООО «Агроснаб»", "0071234567", "supplier"),
    ("out", "Зарплата на кошелёк цифрового рубля сотрудника за март", "Петров Петр", "001234567890", "salary"),
    ("out", "Перевод собственных средств на счет цифрового рубля", "ООО «Вектор»", "0076543210", "own_transfer"),
    ("in", "Перевод собственных средств со счета цифрового рубля на расчетный счет", "ООО «Вектор»", "0076543210", "own_transfer"),
    ("out", "Единый налоговый платеж, оплата цифровыми рублями", "Казначейство России (ФНС России)", "0071000001", "tax"),
    ("out", "Аренда офиса за май, оплата ЦР", "ИП Смирнов", "001112223334", "rent"),
])
def test_digital_ruble_is_just_rubles(clf, direction, purpose, name, inn, want):
    p = _one(clf, direction, purpose, name, inn, 1000.0)
    assert p.category == want, (purpose, p)


def test_digital_ruble_does_not_change_category(clf):
    base = [("out", "Оплата за мясную продукцию по УПД 88", "ООО «Мясной двор»", "0078889990", 143000.0),
            ("out", "Оплата электроэнергии за март", "АО «Энергосбыт»", "0072223334", 23400.0),
            ("in", "Оплата по договору поставки № 12 за продукцию", "ООО «Ромашка»", "0070001112", 267000.0)]
    for d, p, n, i, a in base:
        plain = _one(clf, d, p, n, i, a).category
        for suffix in (" цифровыми рублями", " (цифровой рубль)", ", оплата с кошелька цифрового рубля"):
            assert _one(clf, d, p + suffix, n, i, a).category == plain


@pytest.mark.parametrize("op", [
    Op("out"), Op("in", "", "", "", 0.0), Op("", "   ", "", "", -5.0), Op("вбок", "ааааа", "???", "12", float("nan")),
    Op("out", "x" * 20000, "y" * 5000, "0" * 50, float("inf")), Op("in", "123456", "", "", 1e18),
    Op("out", "🙂💸 ;;; \n\t", "ООО «»", "abc", 1.0), Op("Поступление", None, None, None, None),
])
def test_garbage_does_not_crash(clf, op):
    p = clf.predict([op])[0]
    assert p.category in CATEGORIES and 0.0 <= p.confidence <= 1.0


def test_garbage_is_other(clf):
    for purpose in ("ааааааа", "-", "Платеж", "123456"):
        assert _one(clf, "out", purpose, "ООО «Альфа»", "0082000016", 1000.0).category == "other", purpose


def test_predict_empty_and_batch_order(clf):
    assert clf.predict([]) == []
    ops = [Op("out", "Комиссия за ведение счета", "ПАО «Банк»"), Op("out", "Заработная плата за май", "ПАО «Банк»"),
           Op("out", "Комиссия за ведение счета", "ПАО «Банк»")]
    cats = [p.category for p in clf.predict(ops)]
    assert cats == ["bank_fee", "salary", "bank_fee"]


def test_save_load_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    W = np.zeros((N_FEATURES, len(CATEGORIES)), dtype=np.float32)
    rows = rng.choice(N_FEATURES, 100, replace=False)
    W[rows] = rng.normal(size=(100, len(CATEGORIES)))
    c = Classifier(W, rng.normal(size=len(CATEGORIES)).astype(np.float32), temperature=0.7, min_confidence=0.25)
    c.save(tmp_path)
    d = Classifier.load(tmp_path)
    ops = [Op("out", "Оплата за товар", "ООО «Ромашка»", "0071234567", 1000)]
    assert np.allclose(c.predict_proba(ops), d.predict_proba(ops), atol=1e-2)
    assert d.temperature == 0.7 and d.min_confidence == 0.25


def test_novel_test_set_is_valid():
    df = load_novel(NOVEL)
    assert len(df) >= 250 and df.id.is_unique
    assert set(df.category) <= set(CATEGORIES)
    assert set(df.dir.dropna()) == {"in", "out"} and df.dir.notna().all()
    assert (df.group == "digital_ruble").sum() >= 20


def test_novel_not_in_dataset():
    """Назначения «нового» набора не должны встречаться в датасете (если он есть рядом)."""
    path = NOVEL.parents[3] / "cashflow_dataset_participants" / "all_operations.csv"
    if not path.exists():
        pytest.skip("датасета нет")
    ds = set(pd.read_csv(path, sep=";", encoding="utf-8-sig", usecols=["payment_purpose"]).payment_purpose.dropna())
    df = load_novel(NOVEL)
    assert not (set(df.payment_purpose) - {""}) & ds


def test_extra_rules_valid():
    for r in labels.EXTRA_RULES + labels.FIXES:
        assert r.category in CATEGORIES
        r.compile()


def test_counterparty_weak_labels_do_not_cross_partitions():
    # Only the test partition knows what this name usually means. The empty
    # training operation must not inherit that held-out information.
    df = pd.DataFrame([
        dict(operation_id="train", company_id="A", direction="out", payment_purpose="", counterparty_name="ООО Вектор"),
        dict(operation_id="test", company_id="B", direction="out", payment_purpose="Оплата услуг", counterparty_name="ООО Вектор"),
    ])
    go = pd.DataFrame([dict(id="train", category="other"), dict(id="test", category="services")])
    assert labels.teacher_labels(df, go).iloc[0].label == "services"
    parts = labels.teacher_label_partitions({"train": df.iloc[:1], "test": df.iloc[1:]}, go)
    assert parts["train"].iloc[0].label == "other"
    assert parts["test"].iloc[0].label == "services"
    with pytest.raises(ValueError, match="multiple"):
        labels.teacher_label_partitions({"train": df, "test": df.iloc[1:]}, go)


def test_counterparty_dropout_preserves_only_informative_labels():
    from zavozik_ml.classify.train import counterparty_dropout
    rows = [dict(purpose="Оплата электроэнергии", name="Энергосбыт", inn="0123456789", label="utilities"),
            dict(purpose="", name="Энергосбыт", inn="0123456789", label="utilities")]
    out = counterparty_dropout(rows, 42, rate=1)
    assert len(out) == 3
    assert out[-1] == dict(purpose="Оплата электроэнергии", name="", inn="", inn_type="none", label="utilities")
    assert rows[0]["name"] == "Энергосбыт"  # no mutation of the original data
    assert counterparty_dropout(rows, 42, rate=0) == rows


@pytest.fixture(scope="module")
def stub(clf):
    server, port = build_server("127.0.0.1:0", workers=2, classifier=clf)
    server.start()
    with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
        yield pb_grpc.CategorizerServiceStub(ch)
    server.stop(0)


def test_grpc_classify(stub):
    req = pb.ClassifyRequest(operations=[
        pb.Operation(id="1", direction="out", amount=1000, counterparty_inn="0071234567",
                     counterparty_name="ООО «Агроснаб»", payment_purpose="Оплата поставщику цифровыми рублями за товар"),
        pb.Operation(id="2", direction="in"),
    ])
    resp = stub.Classify(req)
    assert [r.id for r in resp.results] == ["1", "2"]
    assert resp.results[0].category == "supplier"
    assert all(r.category in CATEGORIES for r in resp.results)
    assert resp.model_version.startswith("classifier-v")
    assert stub.Classify(pb.ClassifyRequest()).results == []


def test_grpc_without_artifact():
    server, port = build_server("127.0.0.1:0", workers=1)
    server.start()
    try:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as ch:
            with pytest.raises(grpc.RpcError) as e:
                pb_grpc.CategorizerServiceStub(ch).Classify(pb.ClassifyRequest())
            assert e.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    finally:
        server.stop(0)


@pytest.mark.parametrize('op', [
    pb.Operation(direction='wrong'), pb.Operation(direction='out', amount=float('inf')),
    pb.Operation(direction='out', amount=-1), pb.Operation(direction='out', payment_purpose='x'*8193),
    pb.Operation(direction='in', id='x'*257), pb.Operation(direction='in', counterparty_inn='x'*65),
])
def test_grpc_rejects_invalid_operation(stub, op):
    with pytest.raises(grpc.RpcError) as e:
        stub.Classify(pb.ClassifyRequest(operations=[op]))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_grpc_bounds_total_text_before_classification(stub):
    op=pb.Operation(direction='out', payment_purpose='x'*8000)
    with pytest.raises(grpc.RpcError) as e:
        stub.Classify(pb.ClassifyRequest(operations=[op]*251))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT

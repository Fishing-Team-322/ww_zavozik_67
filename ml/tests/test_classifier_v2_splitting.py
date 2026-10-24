from collections import Counter

import pytest

from zavozik_ml.classify_v2.splitting import TemplateIndex, TemplateRegistry, audit, isolate, template_text
from zavozik_ml.classify_v2.data import training_rows
from zavozik_ml.classify_v2.taxonomy import Taxonomy


def row(i, company, purpose, label="supplier", direction="out"):
    return dict(id=i, company=company, direction=direction, purpose=purpose, name="Example",
                inn_type="org", amount=10000., label=label, source="case_weak")


def parts():
    purposes = ["Покупка по заказу", "Закупка партии", "Приобретение сырья",
                "Доставка комплекта", "Расходы на канцтовары", "Поставка инвентаря"]
    return {p: [row(f"{p}-{i}", p, purpose) for i, purpose in enumerate(purposes)]
            for p in ("train", "calibration", "test")}


def test_date_document_amount_name_direction_and_channel_are_not_group_shortcuts():
    a = "Оплата материалов по счету №123 от 01.02.2026 за март 2026. Без НДС"
    b = "Оплата материалов по договору №999 от 03.04.2025 за июнь 2025 цифровыми рублями"
    assert template_text(a) == template_text(b)
    p = {k: [row(k, k, v, direction="in" if k == "test" else "out")]
         for k, v in zip(("train", "calibration", "test"), (a, b, a))}
    retained, registry, result = isolate(p)
    assert result["family_count"] == 1
    assert sum(bool(r) for r in retained.values()) == 1


def test_near_duplicates_form_connected_families_not_separate_random_rows():
    index = TemplateIndex(["оплата строительных материалов", "погашение кредита"])
    assert "оплата строительных материалов" in index.matches("оплата строителных материалов")
    assert not index.matches("аренда офисного помещения")


def test_generated_goods_service_and_bank_slots_do_not_create_fake_new_templates():
    assert template_text("Оплата за материалы по счету №1") == template_text("Оплата за оборудование по договору №2")
    assert template_text("Аванс за услуги охраны") == template_text("Аванс за транспортные услуги")
    assert template_text("Перевод своих средств в ПАО Сбербанк") == template_text("Перевод своих средств в АО Альфа-Банк")


def test_typo_in_a_masked_slot_cannot_evade_family_ownership():
    p = {"train": [row("a", "train", "Оплата материалов")],
         "calibration": [row("b", "calibration", "Оплата материлов")],
         "test": [row("c", "test", "Оплата оборудования")]}
    kept, registry, result = isolate(p)
    assert result["family_count"] == 1
    assert sum(bool(r) for r in kept.values()) == 1


def test_company_and_family_ownership_is_deterministic_and_audited():
    p = parts()
    kept, registry, result = isolate(p, 42)
    assert all(kept.values())
    assert audit(kept, registry)["passed"]
    assert all(not v for pair in audit(kept, registry)["pairwise_intersections"].values() for v in pair.values())
    reverse = {name: list(reversed(rows)) for name, rows in reversed(list(p.items()))}
    _, repeated, _ = isolate(reverse, 42)
    assert repeated.document() == registry.document()
    assert sum(len(r) for r in kept.values()) == 6


def test_augmentation_cannot_smuggle_a_heldout_family_back_into_train(monkeypatch):
    kept, registry, _ = isolate(parts())
    heldout = kept["test"][0]["purpose"]
    from zavozik_ml.classify import augment

    def malicious_perturb(parent, rng):
        return dict(parent, purpose=heldout)

    monkeypatch.setattr(augment, "perturb", malicious_perturb)
    monkeypatch.setattr(augment, "synth", lambda rng, n: [dict(row("s", "", heldout), source="v1_synth")])
    rows = training_rows(kept["train"], Taxonomy.load(), perturb=10, synth=1, registry=registry)
    assert rows
    assert not any(r["purpose"] == heldout for r in rows)
    assert all(r.get("parent_company") == "train" for r in rows)
    assert audit(dict(kept, train=rows), registry)["passed"]


def test_audit_rejects_hidden_family_collision_even_if_full_input_differs():
    kept, registry, _ = isolate(parts())
    leaked = dict(kept["test"][0], id="forged", company="train", parent_company="train", name="Different")
    with pytest.raises(ValueError, match="leakage"):
        audit(dict(kept, train=kept["train"] + [leaked]), registry)


def test_primary_calibration_cannot_be_augmented():
    kept, registry, _ = isolate(parts())
    kept["calibration"][0]["source"] = "calibration_perturb"
    with pytest.raises(ValueError, match="must not contain"):
        audit(kept, registry)


def test_missing_purpose_teacher_does_not_learn_from_purged_context(tmp_path, monkeypatch):
    import json
    import pandas as pd
    from zavozik_ml.classify import labels
    from zavozik_ml.classify_v2 import data
    source = tmp_path / "source.csv"; source.write_text("mock source")
    split = tmp_path / "split.json"
    split.write_text(json.dumps(dict(calibration_companies=["C"], test_companies=["S"])))
    frame = pd.DataFrame([
        dict(operation_id="context", company_id="T", direction="out", payment_purpose="Оплата аренды",
             counterparty_name="Арендодатель", counterparty_inn="", amount=100.),
        dict(operation_id="empty", company_id="T", direction="out", payment_purpose="",
             counterparty_name="Арендодатель", counterparty_inn="", amount=100.),
        dict(operation_id="cal", company_id="C", direction="out", payment_purpose="Оплата услуг",
             counterparty_name="Сервис", counterparty_inn="", amount=100.),
        dict(operation_id="test", company_id="S", direction="out", payment_purpose="Оплата материалов",
             counterparty_name="Поставщик", counterparty_inn="", amount=100.)])
    go = pd.DataFrame(dict(id=["context", "empty", "cal", "test"], category=["rent", "other", "services", "supplier"]))
    monkeypatch.setattr(labels, "load_dataset", lambda path: frame)
    monkeypatch.setattr(labels, "go_rule_labels", lambda *args: go)

    def purge(provisional, seed):
        assert next(r for r in provisional["train"] if r["id"] == "empty")["label"] == "rent"
        kept = {name: [dict(r, template_family=name, parent_id=r["id"], parent_company=r["company"])
                       for r in rows if r["id"] != "context"] for name, rows in provisional.items()}
        return kept, object(), {"policy": "test purge context before final teacher"}

    monkeypatch.setattr(data, "isolate", purge)
    retained, manifest, _ = data.load_partitions(source, split, tmp_path / "cache")
    assert retained["train"][0]["label"] == "other"
    assert "after template purging" in manifest["statistical_teacher_labels"]

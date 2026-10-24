import json

import pytest

from zavozik_ml.category_discovery.local_teacher import parse_response
from zavozik_ml.category_discovery.semantic_pairs import SCHEMA


def pair():
    return dict(schema=SCHEMA, pair_id="a"*24, partition="train",
                left=dict(content_key="a", id="a", direction="out", purpose="Перечисление заработной платы"),
                right=dict(content_key="b", id="b", direction="out", purpose="Перечислення заробітної плати"),
                coarse=None, fine=None, rationale="", reviewer="", reviewer_kind="")


def response(**updates):
    return json.dumps(dict(coarse="same", fine="same", left_evidence="заработной платы",
                           right_evidence="заробітної плати", rationale="Both descriptions explicitly describe employee pay", **updates), ensure_ascii=False)


def test_grounded_model_proposal_is_always_weak_and_never_human():
    result = parse_response(response(), pair())
    assert result["provenance"] == "local_model_weak"
    assert result["reviewer_kind"] == "local_model"
    assert result["left"] == pair()["left"] and result["right"] == pair()["right"]


def test_invented_or_translated_evidence_is_rejected():
    value = json.loads(response())
    value["right_evidence"] = "salary"
    with pytest.raises(ValueError, match="exact source substring"):
        parse_response(json.dumps(value), pair())


def test_levels_and_null_rationale_are_validated_before_export():
    value = json.loads(response())
    value.update(coarse="different", fine="same")
    with pytest.raises(ValueError, match="fine same"):
        parse_response(json.dumps(value), pair())
    value.update(coarse="same", rationale=None)
    with pytest.raises(ValueError, match="rationale"):
        parse_response(json.dumps(value), pair())


def test_unknown_without_evidence_is_valid_but_economic_same_is_not():
    value = json.loads(response())
    value.update(left_evidence="", coarse="uncertain", fine="uncertain")
    assert parse_response(json.dumps(value), pair())["coarse"] == "uncertain"
    value.update(coarse="same", fine="same")
    with pytest.raises(ValueError, match="without evidence"):
        parse_response(json.dumps(value), pair())

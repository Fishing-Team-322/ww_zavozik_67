import json

import pytest

from zavozik_ml.category_discovery.review_ui import create_page


def test_offline_blind_page_escapes_source_and_has_no_prediction_fields(tmp_path):
    source = tmp_path / "blind.jsonl"
    rows = [dict(pair_id="x", left=dict(purpose="</script><script>alert(1)</script>", direction="out", id="a"),
                 right=dict(purpose="аренда", direction="out", id="b"), judgment=None, reviewer="")]
    source.write_text(json.dumps(rows[0]))
    out = tmp_path / "review.html"
    create_page(source, out)
    html = out.read_text()
    assert "</script><script>alert" not in html
    assert "\\u003c/script" in html
    assert "fetch(" not in html and "XMLHttpRequest" not in html
    assert "predicted_same" not in html
    with pytest.raises(ValueError, match="exists"):
        create_page(source, out)

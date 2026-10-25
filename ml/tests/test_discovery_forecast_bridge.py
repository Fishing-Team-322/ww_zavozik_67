import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from zavozik_ml.category_discovery.forecast_bridge import project_operations,daily_history,forecast_request


def op(identity,purpose,amount=10,direction="out",**extra):
    return dict(id=identity,date="2025-06-01",amount=amount,direction=direction,
                purpose=purpose,counterparty_id="company-scoped-pseudonym",**extra)


def assignment(identity,native="dynamic-x",**extra):
    return dict(id=identity,status="assigned",category_id=native,category_path=["dynamic-parent",native],**extra)


def projection(category):
    return dict(taxonomy_version="taxonomy1",projection_version="projection1",
                categories={"dynamic-x":dict(forecast_category=category)})


def test_native_hierarchy_and_original_invoice_survive_forecast_projection():
    purpose="Оплата по счету № 15 от 01.06.2025 за оборудование"
    result=project_operations([op("a",purpose,semantic_text="оборудование")],
        [assignment("a")],projection("supplier"),taxonomy_version="taxonomy1")
    assert result.transactions[0]["purpose"]==purpose
    assert result.transactions[0]["category"]=="supplier"
    assert result.semantic_assignments[0]["category_id"]=="dynamic-x"
    assert result.semantic_assignments[0]["category_path"]==["dynamic-parent","dynamic-x"]
    with pytest.raises(ValueError,match="versions differ"):
        project_operations([op("a",purpose)],[assignment("a")],projection("supplier"),taxonomy_version="other")
    p=projection('tax');p['fallback']='source_text_evidence_v1'
    explicit=project_operations([op('a','Выплата заработной платы')],[assignment('a')],p,taxonomy_version='taxonomy1')
    assert explicit.transactions[0]['category']=='salary'


def test_internal_flows_excluded_before_daily_totals_but_bank_credit_is_retained():
    ops=[op("own","Перевод между своими счетами",100,"in"),
         op("founder","Заем учредителя",50,"in"),
         op("bank","Получение банковского кредита",200,"in",counterparty_relation="bank"),
         op("goods","Покупка товара",30)]
    result=project_operations(ops,[assignment(o["id"],"dynamic-x" if o["id"]!="goods" else "goods") for o in ops],
        dict(taxonomy_version="taxonomy1",categories={"dynamic-x":dict(forecast_category="own_transfer"),
                                                  "goods":dict(forecast_category="supplier")}),taxonomy_version="taxonomy1")
    assert [r["category"] for r in result.transactions]==["own_transfer","owner_loan","loan_payment","supplier"]
    h=daily_history(result,"2025-06-01","2025-06-03",missing_dates=["2025-06-03"])
    assert h[0]["inflow"]==200 and h[0]["outflow"]==30
    assert h[0]["by_category"]["supplier"]==-30 and h[0]["by_category"]["owner_loan"]==50
    assert h[1]["missing"] is False and h[1]["inflow"]==0
    assert h[2]["missing"] is True


def test_rail_does_not_make_unknown_money_revenue_or_dividends_an_owner_loan():
    result=project_operations([op("a","Выплата дивидендов",counterparty_relation="owner")],
        [assignment("a")],projection("owner_loan"),taxonomy_version="taxonomy1")
    assert result.transactions[0]["category"]=="other"
    with pytest.raises(ValueError,match="internal flow scope"):
        daily_history(result,"2025-06-01","2025-06-01")
    result=project_operations([op("b","Поступление",direction="in")],[assignment("b",channel="sbp")],
        projection("revenue_b2b"),taxonomy_version="taxonomy1")
    assert result.transactions[0]["category"]=="other"
    p=projection("revenue_b2b");p["categories"]["dynamic-x"]["flow_role"]="sales_revenue"
    result=project_operations([op("b","Выручка",direction="in")],[assignment("b",channel="sbp")],p,taxonomy_version="taxonomy1")
    assert result.transactions[0]["category"]=="revenue_sbp"


@pytest.mark.skipif(importlib.util.find_spec("grpc_tools") is None,reason="proto compiler optional")
def test_real_current_proto_round_trip_keeps_transactions_field9(tmp_path):
    # Fresh process avoids collision with the stale generated module imported
    # by the existing serving tests in the parent interpreter.
    root=Path(__file__).resolve().parents[2]
    code="""import sys
from pathlib import Path
from grpc_tools import protoc
root,out=map(Path,sys.argv[1:]);assert protoc.main(['protoc','-I'+str(root/'proto'),'--python_out='+str(out),str(root/'proto/forecast/v1/forecaster.proto')])==0
sys.path.insert(0,str(out))
from forecast.v1.forecaster_pb2 import ForecastRequest
from zavozik_ml.category_discovery.forecast_bridge import project_operations,daily_history,forecast_request
ops=[dict(id='a',date='2025-06-01',amount=77.25,direction='out',purpose='Счет №15 от 01.06.2025',counterparty_id='pseudonym')]
r=project_operations(ops,[],dict(taxonomy_version='v',categories={}),taxonomy_version='v')
h=daily_history(r,'2025-06-01','2025-06-02')
request=forecast_request(ForecastRequest,r,h,company_id='company')
decoded=ForecastRequest.FromString(request.SerializeToString())
assert len(decoded.transactions)==1 and decoded.transactions[0].purpose==ops[0]['purpose']
assert decoded.transactions[0].amount==77.25 and decoded.history[0].outflow==77.25
assert decoded.history[1].date=='2025-06-02' and decoded.flow_scope=='business_without_internal_transfers'
try: forecast_request(ForecastRequest,r,[dict(h[0],outflow=0)],company_id='company')
except ValueError as e: assert 'exceed' in str(e)
else: raise AssertionError('must reject double counting against daily totals')
"""
    r=subprocess.run([sys.executable,"-c",code,str(root),str(tmp_path)],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stdout+r.stderr


def test_cli_requires_explicit_statement_coverage_before_loading_encoder(monkeypatch):
    import sys
    from zavozik_ml.category_discovery import working_server
    monkeypatch.setattr(sys,'argv',['working_server','--model','unused','--input','unused.jsonl','--forecast-output','unused.json'])
    monkeypatch.setattr(working_server,'WorkingModel',lambda *a,**k:pytest.fail('encoder loaded before coverage preflight'))
    with pytest.raises(SystemExit) as exc:working_server.main()
    assert exc.value.code==2

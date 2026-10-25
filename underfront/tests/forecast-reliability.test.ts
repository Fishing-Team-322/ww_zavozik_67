import test from "node:test";
import assert from "node:assert/strict";
import type { Forecast, Gap } from "../src/shared/api";
import { forecastReliability, gapAmount, riskProbability } from "../src/entities/forecast/model/reliability";
import { planFactSeries } from "../src/entities/forecast/model/plan-fact";

const forecast: Forecast = { as_of: "2026-10-24", horizon: 30, model_used: "test", model_version: "1", flow_scope: "business", warnings: [], fallback_used: false, low_confidence: false, opening_balance: 1000, safe_to_spend: 500, status: "ok", headline: "", history: [], markers: [], gaps: [], points: [{date:"2026-11-23", p10: 500, p50: 1000, p90: 1500, is_workday: true}] };
test("spending is unavailable on stale, future, fallback and unverified plans, including legacy API payloads", () => {
  assert.equal(forecastReliability(forecast, "2026-10-25").spendingAvailable,true);
  for(const f of [{...forecast,as_of:"2026-09-29"},{...forecast,as_of:"2026-10-26"},{...forecast,fallback_used:true},{...forecast,low_confidence:true},{...forecast,unconfirmed_recurring:5},{...forecast,spending_available:false}]) {
    assert.equal(forecastReliability(f,"2026-10-25").spendingAvailable,false);
  }
});
test("limited risk probabilities never leak through cards or scenarios",()=>{
  const gap={probability:1} as Gap;
  assert.equal(riskProbability(gap,{...forecast,fallback_used:true}),null);
  assert.equal(riskProbability({...gap,probability_reliable:false},forecast),null);
});
test("a positive median balance does not turn stochastic shortfall into a misleading zero",()=>{
  assert.deepEqual(gapAmount({shortfall:0,shortfall_p90:450000}),{amount:450000,label:"Нехватка в неблагоприятном варианте"});
  assert.equal(gapAmount({shortfall:2000,shortfall_p90:450000}).amount,2000);
  assert.equal(gapAmount({shortfall:0,shortfall_p90:0}).amount,null);
});
test("missing plan stays a gap while actual bank flows remain visible",()=>{
  const rows=[{period:"2026-10-24",plan_in:null,plan_out:null,fact_in:100,fact_out:20,observed:true,deviation:null,plan_available:false}];
  assert.deepEqual(planFactSeries(rows,"net"),[{date:"2026-10-24",plan:null,fact:80,deviation:null}]);
});

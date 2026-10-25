import test from 'node:test';
import assert from 'node:assert/strict';
import { planFactProbability, planFactSeries, type SavedForecastChange } from '../src/entities/forecast/model/plan-fact';

test('plan/fact graph preserves unknown actuals and distinguishes net from gross flows',()=>{
  const rows=[{period:'2026-10-23',plan_in:100,plan_out:30,fact_in:80,fact_out:40,deviation:-30,observed:true},{period:'2026-10-24',plan_in:10,plan_out:0,fact_in:null,fact_out:null,deviation:null,observed:false}];
  assert.deepEqual(planFactSeries(rows,'net'),[{date:'2026-10-23',plan:70,fact:40,deviation:-30},{date:'2026-10-24',plan:10,fact:null,deviation:null}]);
  assert.equal(planFactSeries(rows,'out')[0].fact,40);
  assert.equal(planFactSeries(rows,'in')[1].fact,null);
});

test('saved risk percentages need independent reliability for each revision, including legacy responses', () => {
  const change: SavedForecastChange = { gap_date: '2026-11-01', gap_date_before: null, probability_before: 0, probability_after: 1, revision_before: 11, revision_after: 12 };
  assert.equal(planFactProbability(change, 'before'), null);
  assert.equal(planFactProbability(change, 'after'), null);
  const limited = { ...change, probability_reliable_before: false, probability_reliable_after: true };
  assert.equal(planFactProbability(limited, 'before'), null);
  assert.equal(planFactProbability(limited, 'after'), 1);
  for (const value of [null, NaN, Infinity, -0.01, 1.01]) {
    assert.equal(planFactProbability({ ...limited, probability_after: value }, 'after'), null);
  }
});

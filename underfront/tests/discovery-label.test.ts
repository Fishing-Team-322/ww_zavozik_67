import test from "node:test";
import assert from "node:assert/strict";
import {discoveryLabel} from "../src/entities/company/model/discovery";
test("native labels preserve abstention and never present a similarity probability",()=>{
 assert.equal(discoveryLabel(undefined),null);
 assert.equal(discoveryLabel({status:"unknown",similarity:.99}),"Группа не определена");
 assert.equal(discoveryLabel({status:"ambiguous"}),"Группу нужно уточнить");
 assert.equal(discoveryLabel({status:"assigned",coarse_category_title:"Труд",category_title:"Зарплата"}),"Предварительная группа: Труд / Зарплата");
});

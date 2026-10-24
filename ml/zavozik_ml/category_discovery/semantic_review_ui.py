"""Standalone offline two-level review, without predictions or network calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from zavozik_ml.classify_v2.model import sha256_file
from .corpus import read_rows
from .semantic_pairs import SCHEMA


def build(review: Path, partition: str, out: Path):
    if out.exists():
        raise ValueError("refuse overwrite of review UI")
    meta = json.loads((review / "manifest.json").read_text())
    source = review / f"{partition}_blind.jsonl"
    if meta["schema"] != SCHEMA or sha256_file(source) != meta["partitions"][partition]["blind_sha256"]:
        raise ValueError("review source changed")
    rows = read_rows(source)
    if any(r["coarse"] is not None or r["fine"] is not None for r in rows):
        raise ValueError("blind source contains judgments")
    payload = json.dumps(dict(rows=rows, key=sha256_file(source), partition=partition,
                              instructions=meta["instructions"]), ensure_ascii=False).replace("<", "\\u003c")
    html = '''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Экономический смысл — слепая проверка пар</title>
<style>body{font:17px system-ui;background:#f4f5f2;color:#20281e;margin:0}main{max-width:980px;margin:30px auto;padding:24px}h1{font-size:28px}pre{white-space:pre-wrap;font:15px system-ui}article{background:white;padding:24px;border:1px solid #ccd2c7;border-radius:12px;margin:16px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}.purpose{white-space:pre-wrap;line-height:1.6}button,input,textarea,select{font:inherit;padding:10px;border:1px solid #a9b3a2;border-radius:6px}button{cursor:pointer;background:white;margin:5px}button[aria-pressed=true]{background:#244a36;color:white}textarea{width:95%;min-height:80px}small{color:#566151}#error{color:#a62929}@media(max-width:640px){.pair{grid-template-columns:1fr}main{margin:0;padding:16px}}</style>
<main><h1>Экономический смысл платежей</h1><p id="progress"></p>
<details><summary>Критерии и ограничения</summary><pre id="instructions"></pre><p>Это внутренний синтетический корпус. Его разметка не доказывает качество на настоящих банковских выписках. Ответы остаются в этом браузере до экспорта.</p></details>
<article><label>Разметчик <input id="reviewer" placeholder="Имя или постоянный ID"></label>
<label>Кто размечает? <select id="kind"><option value="">Выберите</option><option value="human">Человек</option><option value="agent">Агент</option><option value="local_model">Локальная модель</option></select></label></article>
<article class="pair"><section><small id="leftmeta"></small><p class="purpose" id="left"></p></section><section><small id="rightmeta"></small><p class="purpose" id="right"></p></section></article>
<article><p>Одна крупная экономическая природа?</p><div id="coarse"></div><p>Одна подробная группа?</p><div id="fine"></div><p><label for="rationale">Обоснование по текстам (без додумывания)</label></p><textarea id="rationale"></textarea><p id="error" role="alert"></p></article>
<button id="prev">← Предыдущая</button><button id="next">Следующая →</button><button id="export">Экспорт JSONL</button><p><small>Сходство слов, направление и канал сами по себе не доказывают одинаковый экономический смысл. «Не хватает сведений» — допустимый ответ.</small></p></main>
<script id="data" type="application/json">PAYLOAD</script><script>
const data=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
const storageKey='economic-pairs-v2:'+data.key;
let saved;try{saved=JSON.parse(localStorage.getItem(storageKey)||'null')}catch(e){saved=null}
let state=saved&&saved.hash===data.key?saved:{hash:data.key,index:0,answers:{},reviewer:'',kind:''};
const labels={same:'Одинаковые',different:'Разные',uncertain:'Не хватает сведений'};
function current(){return data.rows[state.index]}
function answer(){const r=current();if(!r)return null;return state.answers[r.pair_id]||={coarse:null,fine:null,rationale:''}}
function persist(){state.reviewer=$('reviewer').value.trim();state.kind=$('kind').value;localStorage.setItem(storageKey,JSON.stringify(state))}
function valid(a){if(!a||!a.coarse||!a.fine)return 'Нужны ответы на обоих уровнях.';if(a.fine==='same'&&a.coarse!=='same')return 'Одна подробная группа должна иметь одну крупную природу.';if(a.coarse==='different'&&a.fine!=='different')return 'Разная крупная природа требует разных подгрупп.';if(!a.rationale.trim())return 'Добавьте обоснование.';return ''}
function render(){const r=current(),a=answer();$('progress').textContent=data.partition+' · пара '+(r?state.index+1:0)+' из '+data.rows.length+' · заполнено '+Object.values(state.answers).filter(x=>!valid(x)).length;
for(const side of ['left','right']){$(side).textContent=r?r[side].purpose:'Нет подходящих пар';$(side+'meta').textContent=r?r[side].id+' · '+(r[side].direction==='in'?'Поступление':'Списание'):''}
for(const level of ['coarse','fine']){$(level).replaceChildren();for(const [value,label]of Object.entries(labels)){const b=document.createElement('button');b.textContent=label;b.setAttribute('aria-pressed',String(a&&a[level]===value));b.onclick=()=>{if(!a)return;a[level]=value;persist();render()};$(level).append(b)}}
$('rationale').value=a?a.rationale:'';$('error').textContent=a&&a.coarse&&a.fine?valid(a):'';$('prev').disabled=state.index===0;$('next').disabled=state.index>=data.rows.length-1}
$('reviewer').value=state.reviewer;$('kind').value=state.kind;$('instructions').textContent=data.instructions;
$('reviewer').oninput=persist;$('kind').onchange=persist;$('rationale').oninput=()=>{const a=answer();if(a)a.rationale=$('rationale').value;persist()};
function move(delta){persist();state.index=Math.max(0,Math.min(data.rows.length-1,state.index+delta));persist();render()}
$('prev').onclick=()=>move(-1);$('next').onclick=()=>move(1);
$('export').onclick=()=>{persist();if(!state.reviewer||!state.kind){$('error').textContent='Укажите разметчика и источник ответов.';return}
const result=data.rows.map(r=>{const a=state.answers[r.pair_id];return a&&!valid(a)?{...r,...a,reviewer:state.reviewer,reviewer_kind:state.kind}:r});
const blob=new Blob([result.map(r=>JSON.stringify(r)).join('\\n')+'\\n'],{type:'application/x-ndjson;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=data.partition+'-reviewed-'+state.reviewer.replace(/[^a-zа-я0-9_-]/gi,'_')+'.jsonl';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
render();
</script></html>'''.replace("PAYLOAD", payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return dict(partition=partition, pairs=len(rows), source_sha256=sha256_file(source), html_sha256=sha256_file(out))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--review", type=Path, required=True)
    p.add_argument("--partition", choices=("train", "calibration", "test"), required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.review, a.partition, a.out), indent=2))


if __name__ == "__main__":
    main()

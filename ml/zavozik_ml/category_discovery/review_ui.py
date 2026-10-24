"""Generate a completely offline blind annotation page; no network or model answers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .corpus import read_rows
from zavozik_ml.classify_v2.model import sha256_file

PAGE = r'''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Слепая проверка смысловых пар</title>
<style>
body{font:17px/1.5 system-ui;background:#f4f6f8;color:#16212d;max-width:1000px;margin:40px auto;padding:0 20px}
article{background:white;border:1px solid #dce2e7;border-radius:14px;padding:24px;margin:16px 0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}pre{white-space:pre-wrap;font:inherit;overflow-wrap:anywhere}
button,input{font:inherit;border:1px solid #acb7c3;border-radius:8px;padding:10px 16px;margin:4px;background:white}
button{cursor:pointer}button.chosen{background:#184f86;color:white}small{color:#516174}nav{display:flex;justify-content:space-between}
progress{width:100%}#status{min-height:30px}@media(max-width:650px){.pair{grid-template-columns:1fr}body{margin:16px auto}}
</style>
<h1>Одинаковый экономический смысл?</h1>
<p>Оценивай назначение денег, а не совпадение слов, контрагента или канала оплаты.
«Одинаковый» — операции можно отнести к одной достаточно подробной смысловой группе.
Если информации мало или уровень детализации спорный, выбирай «Не уверен».
Названия и ответы модели скрыты.</p>
<p><label>Кто размечает <input id="reviewer" placeholder="Имя или псевдоним" autocomplete="off"></label></p>
<small>Данные остаются в этом файле и локальном хранилище браузера. Страница не делает сетевых запросов.
Экспортируй JSONL и сохрани рядом с исходной проверкой. Для независимой оценки не смотри private_sampling_key.</small>
<progress id="progress" value="0" max="1"></progress><div id="status"></div>
<div class="pair"><article><small id="leftDirection"></small><pre id="left"></pre></article>
<article><small id="rightDirection"></small><pre id="right"></pre></article></div>
<div id="choices"><button data-value="same">1 · Одинаковый</button><button data-value="different">2 · Разный</button>
<button data-value="uncertain">3 · Не уверен</button><button data-value="">Снять ответ</button></div>
<nav><button id="prev">← Назад</button><button id="next">Вперёд →</button></nav>
<p><button id="export">Скачать размеченный JSONL</button></p><small id="notice"></small>
<script>
const original=__ROWS__, storageKey='blind-pair-review-__HASH__';
let rows=structuredClone(original), index=0;
const $=id=>document.getElementById(id);
try{const saved=JSON.parse(localStorage.getItem(storageKey));
if(saved&&saved.rows&&saved.rows.length===rows.length&&saved.rows.every((r,i)=>r.pair_id===rows[i].pair_id)){
rows=saved.rows;$('reviewer').value=saved.reviewer||'';index=saved.index||0;}}
catch(e){$('notice').textContent='Локальное сохранение недоступно. Экспортируй результаты перед закрытием.';}
function save(){try{localStorage.setItem(storageKey,JSON.stringify({rows,index,reviewer:$('reviewer').value}));}catch(e){}}
function draw(){const r=rows[index];if(!r){$('status').textContent='Пары отсутствуют';return;}
$('left').textContent=r.left.purpose||'Назначение отсутствует';$('right').textContent=r.right.purpose||'Назначение отсутствует';
$('leftDirection').textContent=r.left.direction==='in'?'Поступление':'Списание';
$('rightDirection').textContent=r.right.direction==='in'?'Поступление':'Списание';
const done=rows.filter(v=>v.judgment!==null).length;$('progress').max=rows.length;$('progress').value=done;
$('status').textContent=`Пара ${index+1} из ${rows.length}. Размечено ${done}.`;
for(const b of document.querySelectorAll('[data-value]'))b.classList.toggle('chosen',b.dataset.value===r.judgment);
$('prev').disabled=index===0;$('next').disabled=index===rows.length-1;save();}
function answer(value){if(!$('reviewer').value.trim()){alert('Укажи, кто размечает, чтобы ответы имели происхождение.');return;}
rows[index].judgment=value||null;rows[index].reviewer=value?$('reviewer').value.trim():'';draw();}
for(const b of document.querySelectorAll('[data-value]'))b.onclick=()=>answer(b.dataset.value);
$('prev').onclick=()=>{index=Math.max(0,index-1);draw();};$('next').onclick=()=>{index=Math.min(rows.length-1,index+1);draw();};
$('reviewer').oninput=save;
document.onkeydown=e=>{if(e.target.tagName==='INPUT')return;
if(e.key==='1')answer('same');if(e.key==='2')answer('different');if(e.key==='3')answer('uncertain');
if(e.key==='ArrowLeft')$('prev').click();if(e.key==='ArrowRight')$('next').click();};
$('export').onclick=()=>{const url=URL.createObjectURL(new Blob([rows.map(r=>JSON.stringify(r)).join('\n')+'\n'],{type:'application/x-ndjson'}));
const a=document.createElement('a');a.href=url;a.download='reviewed_pairs.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
draw();
</script></html>'''


def create_page(blind: Path, out: Path):
    if out.exists():
        raise ValueError("annotation page exists")
    rows = read_rows(blind)
    if any(r.get("judgment") is not None for r in rows):
        raise ValueError("blind annotation must start with empty judgments")
    # Never include any private sampling keys, predictions or HTML from data.
    allowed = {"pair_id", "left", "right", "judgment", "reviewer"}
    if any(set(r) != allowed for r in rows):
        raise ValueError("unexpected fields in blind input")
    data = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    out.write_text(PAGE.replace("__ROWS__", data).replace("__HASH__", sha256_file(blind)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--blind", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    create_page(a.blind, a.out)
    print(a.out.resolve())


if __name__ == "__main__":
    main()

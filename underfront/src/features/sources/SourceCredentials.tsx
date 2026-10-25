"use client";
import { ContentText } from "@/src/shared/ui/content";
import { useState } from "react";
import { api, message } from "@/src/shared/api";
import { Button, Dialog, Input, Select } from "@/src/shared/ui";

export function SourceCredentials({ id, kind, onChanged, triggerLabel = "Доступ и параметры" }: { id: string; kind: string; onChanged: () => void; triggerLabel?: string }) {
  const [open,setOpen]=useState(false); const [busy,setBusy]=useState(false); const [error,setError]=useState("");
  const [key,setKey]=useState(""); const [access,setAccess]=useState("api_key"); const [account,setAccount]=useState("");
  const [from,setFrom]=useState(""); const [to,setTo]=useState(""); const [sheet,setSheet]=useState(""); const [range,setRange]=useState("");
  if (!["gsheets","onec_odata","wb","ozon"].includes(kind)) return null;
  function close(){if(busy)return;setOpen(false);setKey("");setAccount("");setError("");setFrom("");setTo("");setSheet("");setRange("");}
  async function save(event:React.FormEvent){
    event.preventDefault();if(busy)return;setBusy(true);setError("");
    const config:Record<string,string>={};
    if(key){if(kind==="gsheets"){config.api_key="";config.access_token="";config[access]=key;}else config[kind==="onec_odata"?"password":"api_key"]=key;}
    if(account)config[kind==="onec_odata"?"username":"client_id"]=account;
    if(from)config.from=from;if(to)config.to=to;if(sheet)config.spreadsheet_id=sheet;if(range)config.range=range;
    if(!Object.keys(config).length){setError("Заполните хотя бы одно новое значение.");setBusy(false);return;}
    try{await api.request(`/v1/sources/${id}`,{method:"PATCH",json:{config}});setKey("");setOpen(false);onChanged();}
    catch(cause){setError(message(cause));}finally{setBusy(false);}
  }
  return <><Button size="sm" variant="outline" onClick={()=>setOpen(true)}>{triggerLabel}</Button><Dialog open={open} title="Обновить подключение" onClose={close} dismissDisabled={busy}><form onSubmit={save} className="space-y-3"><ContentText variant="body" >Заполненные поля заменят сохранённые значения. Пустые поля сохраняют прежние настройки. Секреты не показываются. После сохранения нажмите «Проверить» у источника.</ContentText>
    {kind==="gsheets"&&<><Input label="Новый ID таблицы" value={sheet} onChange={e=>setSheet(e.target.value)}/><Input label="Новый диапазон таблицы" value={range} onChange={e=>setRange(e.target.value)}/><Select density="form" label="Тип нового ключа" value={access} onChange={e=>setAccess(e.target.value)} options={[{value:"api_key",label:"API key"},{value:"access_token",label:"Access token"}]}/></>}
    {(kind==="ozon"||kind==="onec_odata")&&<Input label={kind==="ozon"?"Новый Client ID":"Новый логин 1С"} value={account} onChange={e=>setAccount(e.target.value)} autoComplete="off"/>}
    <Input label={kind==="onec_odata"?"Новый пароль 1С":"Новый ключ доступа"} type="password" autoComplete="new-password" value={key} onChange={e=>setKey(e.target.value)}/>
    {(kind==="wb"||kind==="ozon")&&<><Input label="Новый период с" type="date" value={from} onChange={e=>setFrom(e.target.value)}/><Input label="Новый период по" type="date" value={to} onChange={e=>setTo(e.target.value)}/></>}
    {error&&<p role="alert">{error}</p>}<Button disabled={busy}>Сохранить параметры</Button></form></Dialog></>;
}

import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

const api=process.env.E2E_API_URL || 'http://localhost:8080';
const dateAt=offset=>{const d=new Date();d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10);};
async function workspace(page,request,age=1){
  const email=`business-audit-${randomUUID()}@example.invalid`, password='Synthetic-audit-2026!';
  const registration=await request.post(`${api}/v1/auth/register`,{data:{email,password,consent_pd:true}});expect(registration.status()).toBe(201);
  const headers={Authorization:`Bearer ${(await registration.json()).access_token}`};
  const company=await request.post(`${api}/v1/companies`,{headers,data:{name:'Проверка бизнес-сценариев',legal_form:'ООО',industry:'services'}});expect(company.status()).toBe(201);
  const cid=(await company.json()).id,base=`${api}/v1/companies/${cid}`;
  async function upload(csv){
    const response=await request.post(`${base}/uploads`,{headers,multipart:{file:{name:'business-audit.csv',mimeType:'text/csv',buffer:Buffer.from(csv)}}});expect(response.status()).toBe(202);
    const job=(await response.json()).id;
    await expect.poll(async()=>(await(await request.get(`${api}/v1/jobs/${job}`,{headers})).json()).status,{timeout:90000}).toBe('done');
    await expect.poll(async()=>(await(await request.get(`${base}/updates`,{headers})).json()).pending_jobs,{timeout:90000}).toBe(0);
  }
  const header='operation_date;amount;direction;counterparty_name;payment_purpose;balance_eod;operation_id\n';
  let csv=header;
  for(let i=90;i>=age;i--){csv+=`${dateAt(-i)};1000;in;Клиент ${i};Оплата услуг;100000;in-${i}\n${dateAt(-i)};1000;out;Поставщик ${i};Оплата материалов;100000;out-${i}\n`;}
  await upload(csv);
  await page.goto('/login');await page.getByLabel('Электронная почта',{exact:true}).fill(email);await page.getByLabel('Пароль',{exact:true}).fill(password);await page.getByRole('button',{name:'Войти',exact:true}).click();await expect(page).toHaveURL(/\/overview$/);
  return {base,headers,cid,upload,header};
}
test('old statements never advertise current cash and limited risk probability is consistent',async({page,request})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const {base,headers}=await workspace(page,request,26);
  await expect(page.getByRole('alert').filter({hasText:'Текущий остаток неизвестен'})).toBeVisible();
  const kpis=page.getByRole('region',{name:'Ключевые показатели'});
  await expect(kpis).toContainText('Нет рекомендации');
  await expect(page.getByText('Без критических рисков',{exact:true})).toHaveCount(0);
  const dashboard=await(await request.get(`${base}/dashboard`,{headers})).json();
  expect(dashboard.forecast.spending_available).toBe(false);expect(dashboard.safe_to_spend).toBe(0);
  const shots=process.env.E2E_SCREENSHOTS_DIR||path.resolve('test-results/screenshots');mkdirSync(shots,{recursive:true});await page.screenshot({path:path.join(shots,'business-stale-statement-fixed.png')});
  expect(errors).toEqual([]);
});
test('invoice refines one calendar payment and risk wording stays consistent',async({page,request})=>{
  const {base,headers}=await workspace(page,request);
  const event=await request.post(`${base}/events`,{headers,data:{date:dateAt(2),amount:10000,direction:'out',title:'Ремонт оборудования',counterparty_name:'Сервис оборудования',additional:true}});expect(event.status()).toBe(201);
  const before=await(await request.get(`${base}/forecast`,{headers})).json();
  await page.goto('/documents');await page.getByRole('button',{name:'Добавить счёт',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByLabel('Номер',{exact:true}).fill('AUDIT-REFINEMENT');await dialog.getByLabel('Контрагент',{exact:true}).fill('Сервис оборудования');await dialog.getByLabel('Сумма, ₽',{exact:true}).fill('250000');
  await dialog.getByRole('combobox',{name:'Направление',exact:true}).click();await page.getByRole('option',{name:'Полученный счёт',exact:true}).click();
  await dialog.getByLabel('Срок оплаты',{exact:true}).fill(dateAt(3));await dialog.getByLabel('Ожидаемая дата оплаты',{exact:true}).fill(dateAt(3));
  await dialog.getByRole('combobox',{name:'Как учесть в прогнозе',exact:true}).click();await page.getByRole('option',{name:'Уточнение платежа из календаря',exact:true}).click();
  await dialog.getByRole('combobox',{name:'Какой платёж уточнить',exact:true}).click();await page.getByRole('option',{name:/Ремонт оборудования/}).click();
  await dialog.getByRole('button',{name:'Сохранить',exact:true}).click();await expect(dialog).toHaveCount(0);
  const after=await(await request.get(`${base}/forecast`,{headers})).json();
  expect(after.points.at(-1).p50).toBeCloseTo(before.points.at(-1).p50-240000,2);
  await page.goto('/forecast');await expect(page.getByText('Возможен кассовый разрыв',{exact:true})).toBeVisible();await expect(page.getByText('Точная вероятность недоступна',{exact:true})).toBeVisible();
  await expect(page.getByText('100%',{exact:true})).toHaveCount(0);
  await page.goto('/risks');await expect(page.getByText('Точная вероятность недоступна',{exact:true})).toBeVisible();
  await expect(page.getByText('Нехватка по базовому прогнозу',{exact:true})).toBeVisible();
  const shots=process.env.E2E_SCREENSHOTS_DIR||path.resolve('test-results/screenshots');mkdirSync(shots,{recursive:true});await page.screenshot({path:path.join(shots,'business-risk-fixed.png')});
  await page.goto('/plan-fact');await expect(page.getByText('План отсутствовал',{exact:true}).first()).toBeVisible();
});
test('confirmed marketplace payout affects plans once and never creates bank cash',async({page,request})=>{
  test.skip(process.env.E2E_INTEGRATION_SANDBOX!=='1','Requires explicitly isolated synthetic integrations.');
  const {base,headers}=await workspace(page,request);
  const source=await request.post(`${base}/sources`,{headers,data:{kind:'wb',title:'Синтетический WB',config:{api_key:'sandbox-key',from:dateAt(-20),to:dateAt(-1)}}});expect(source.status()).toBe(201);
  const sid=(await source.json()).id;
  const sync=await request.post(`${api}/v1/sources/${sid}/sync`,{headers});expect(sync.status()).toBe(202);
  const job=(await sync.json()).id;await expect.poll(async()=>(await(await request.get(`${api}/v1/jobs/${job}`,{headers})).json()).status).toBe('done');
  await page.goto('/sources');await page.getByRole('button',{name:/^Маркетплейсы Wildberries/}).click();
  await page.getByRole('button',{name:'Запланировать подтверждённую выплату',exact:true}).first().click();
  const dialog=page.getByRole('dialog',{name:'Ожидаемая выплата маркетплейса',exact:true});
  await dialog.getByLabel('Подтверждённая дата выплаты',{exact:true}).fill(dateAt(2));await dialog.getByLabel('Сумма к перечислению, ₽',{exact:true}).fill('12345');await dialog.getByLabel('Плательщик в банковской выписке',{exact:true}).fill('ООО Площадка');
  await dialog.getByText('Подтверждаю сумму, срок и отсутствие такого платежа в календаре',{exact:true}).click();await dialog.getByRole('button',{name:'Добавить ожидаемую выплату',exact:true}).click();await expect(dialog).toHaveCount(0);
  const events=await(await request.get(`${base}/events`,{headers})).json();const payout=events.find(event=>event.source_ref?.startsWith('wb'));
  expect(payout.amount).toBe(12345);expect(payout.date).toBe(dateAt(2));
  const retry=await request.post(`${base}/events`,{headers,data:{request_id:payout.request_id,title:payout.title,date:payout.date,amount:payout.amount,direction:'in',counterparty_name:payout.counterparty.name,category:payout.category,additional:true,probability:1,source_ref:payout.source_ref}});expect(retry.status()).toBe(201);expect((await retry.json()).id).toBe(payout.id);
  const operations=await(await request.get(`${base}/operations?q=Площадка`,{headers})).json();expect(operations.items).toHaveLength(0);
});

import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

test('confirmed tax reaches the forecast and plan-fact observes a new statement without reload', async ({page,request}) => {
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const api=process.env.E2E_API_URL||'http://localhost:8080';
  const email=`case-ui-${randomUUID()}@example.invalid`, password='Synthetic-case-2026!';
  const registration=await request.post(`${api}/v1/auth/register`,{data:{email,password,consent_pd:true}});expect(registration.status()).toBe(201);
  const headers={Authorization:`Bearer ${(await registration.json()).access_token}`};
  const created=await request.post(`${api}/v1/companies`,{headers,data:{name:'Синтетический налоговый сценарий',legal_form:'ООО',industry:'services'}});expect(created.status()).toBe(201);const cid=(await created.json()).id;
  const base=`${api}/v1/companies/${cid}`;
  let balance=25000;const end=new Date('2026-10-21T00:00:00Z');
  const csvHeader='date;amount;direction;counterparty;purpose;balance;id\n';let csv=csvHeader;
  for(let i=119;i>=0;i--){const dt=new Date(end);dt.setUTCDate(dt.getUTCDate()-i);const date=dt.toISOString().slice(0,10);const weekday=![0,6].includes(dt.getUTCDay());const incoming=weekday?2000:0,outgoing=weekday?1900:0;balance+=incoming-outgoing;csv+=`${date};${incoming};in;Тестовый клиент;Оплата услуг по договору;${balance};case-in-${i}\n${date};${outgoing};out;Тестовый поставщик;Оплата материалов;${balance};case-out-${i}\n`;}
  async function upload(content){const response=await request.post(`${base}/uploads`,{headers,multipart:{file:{name:'case.csv',mimeType:'text/csv',buffer:Buffer.from(content)}}});expect(response.status()).toBe(202);const job=(await response.json()).id;await expect.poll(async()=>(await(await request.get(`${api}/v1/jobs/${job}`,{headers})).json()).status,{timeout:120000}).toBe('done');await expect.poll(async()=>(await(await request.get(`${base}/updates`,{headers})).json()).pending_jobs,{timeout:120000}).toBe(0);}
  await upload(csv);
  await page.goto('/login');await page.getByLabel('Электронная почта',{exact:true}).fill(email);await page.getByLabel('Пароль',{exact:true}).fill(password);await page.getByRole('button',{name:'Войти',exact:true}).click();await expect(page).toHaveURL(/\/overview$/);
  await page.goto('/taxes');await expect(page.getByRole('heading',{name:'Налоги и обязательные платежи',exact:true})).toBeVisible();
  await page.getByLabel('Название обязательства',{exact:true}).fill('Проверочный налог');await page.getByLabel('Налоговый год',{exact:true}).fill('2026');await page.getByLabel('Подтверждённая сумма, ₽',{exact:true}).fill('90000');await page.getByLabel('Откуда получена сумма',{exact:true}).fill('Синтетическая декларация');
  const treatment=page.getByRole('combobox',{name:'Как учесть в прогнозе',exact:true});
  const confirmed=page.getByRole('checkbox',{name:'Подтверждаю сумму и отсутствие второго обязательства на тот же платёж',exact:true});
  // The shared checkbox hides the native input under a styled label. Exercise
  // its keyboard interaction rather than clicking the decorative overlay.
  await expect(treatment).toContainText('Новый платёж');
  await confirmed.press('Space');await expect(confirmed).toBeChecked();
  await page.getByRole('button',{name:'Рассчитать график платежей',exact:true}).click();await expect(page.getByText('Проверьте перед сохранением',{exact:true})).toBeVisible();await page.getByRole('button',{name:'Подтвердить и добавить',exact:true}).click();await expect(page.getByText('Обязательство сохранено. Календарь и прогноз обновятся автоматически.',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:/Проверочный налог/})).toBeVisible();
  const screenshotDir=process.env.E2E_SCREENSHOTS_DIR||path.resolve('test-results/screenshots');mkdirSync(screenshotDir,{recursive:true});await page.screenshot({path:path.join(screenshotDir,'taxes-synthetic.png'),fullPage:true});
  await page.goto('/forecast');await expect(page.getByText('Возможен кассовый разрыв',{exact:true})).toBeVisible();
  const event=await request.post(`${base}/events`,{headers,data:{title:'Поступление для проверки обновлений',date:'2026-10-21',amount:777777.77,direction:'in',counterparty_name:'Отдельный клиент'}});expect(event.status()).toBe(201);
  await page.goto('/plan-fact');await expect(page.getByRole('img',{name:'График плана и факта: пропуски выписки не заменяются нулём'})).toBeVisible();await expect(page.getByText('Пропущенных платежей нет',{exact:true})).toBeVisible();
  let update=csvHeader;for(let i=1;i<=3;i++){const dt=new Date(end);dt.setUTCDate(dt.getUTCDate()+i);const date=dt.toISOString().slice(0,10);const weekday=![0,6].includes(dt.getUTCDay());const incoming=weekday?2000:0,outgoing=weekday?1900:0;balance+=incoming-outgoing;update+=`${date};${incoming};in;Тестовый клиент;Оплата услуг по договору;${balance};new-in-${i}\n${date};${outgoing};out;Тестовый поставщик;Оплата материалов;${balance};new-out-${i}\n`;}
  await upload(update);
  await expect(page.getByRole('row').filter({hasText:'Поступление для проверки обновлений'})).toBeVisible({timeout:30000});
  await page.screenshot({path:path.join(screenshotDir,'plan-fact-synthetic.png'),fullPage:true});
  const alerts=await request.get(`${base}/alerts?kind=missed_payment`,{headers});expect((await alerts.json()).items.length).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

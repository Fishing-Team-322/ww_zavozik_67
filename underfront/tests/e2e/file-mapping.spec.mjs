import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

test('browser registration and XLSX mapping preserve cents, zero balance and duplicates',async({page,request})=>{
 const email=`xlsx-${randomUUID()}@example.invalid`;const password='E2e!A1b2C3d4';
 await page.goto('/register');await page.getByLabel('Электронная почта',{exact:true}).fill(email);
 await page.getByRole('button',{name:'Продолжить',exact:true}).click();
 await page.getByLabel('Пароль',{exact:true}).fill(password);await page.getByLabel('Повторите пароль',{exact:true}).fill(password);
 await page.getByText('Согласен на обработку персональных данных',{exact:true}).click();
 await expect(page.getByLabel('Согласен на обработку персональных данных',{exact:true})).toBeChecked();
 await page.getByRole('button',{name:'Создать аккаунт',exact:true}).click();await expect(page).toHaveURL(/\/companies\/new$/);
 await page.getByLabel('Название компании',{exact:true}).fill('Synthetic XLSX mapping');await page.getByLabel('Вид деятельности',{exact:true}).fill('Tests');
 await page.getByRole('button',{name:'Создать компанию',exact:true}).click();await expect(page).toHaveURL(/\/sources$/);
 const api=process.env.E2E_API_URL||'http://localhost:8080';const login=await request.post(`${api}/v1/auth/login`,{data:{email,password}});expect(login.status()).toBe(200);
 const headers={Authorization:`Bearer ${(await login.json()).access_token}`};const profile=await request.get(`${api}/v1/me`,{headers});const cid=(await profile.json()).companies[0].id;
 const file=page.locator('input[accept=".csv,.xlsx,.txt,.1c"]');
 const mapping=page.locator('section').filter({has:page.getByRole('heading',{name:'Сопоставление колонок',exact:true})});
 for(let run=0;run<2;run++){
  await file.setInputFiles(path.resolve('tests/fixtures/mapping.xlsx'));
  await expect(mapping).toBeVisible();
  for(const [label,column] of [['Дата *','booked'],['Сумма *','value'],['Направление','flow'],['Остаток на конец дня','closing']]){
   await mapping.getByRole('button',{name:label,exact:true}).click();await page.getByRole('option',{name:column,exact:true}).click();
  }
  await mapping.getByRole('button',{name:'Запустить импорт',exact:true}).click();
  const report=page.locator('section').filter({has:page.getByRole('heading',{name:'Результат импорта',exact:true})});
  await expect(report).toContainText(`Добавлено: ${run===0?'1':'0'}`,{timeout:60000});
  if(run===1)await expect(report).toContainText('Дубли: 1');
 }
 const operations=await request.get(`${api}/v1/companies/${cid}/operations`,{headers});const items=(await operations.json()).items;
 expect(items).toHaveLength(1);expect(items[0].amount).toBe(100.01);
 const dashboard=await request.get(`${api}/v1/companies/${cid}/dashboard`,{headers});expect((await dashboard.json()).balance_now).toBe(0);
 await page.reload();await expect(page.getByRole('heading',{name:'Источники данных',exact:true})).toBeVisible();
});

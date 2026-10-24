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
 await page.getByRole('button',{name:/^Банковская выписка/}).click();
 const file=page.locator('input[accept=".csv,.xlsx,.txt,.1c"]');
 const mapping=page.locator('section').filter({has:page.getByRole('heading',{name:'Сопоставление колонок',exact:true})});
 for(let run=0;run<2;run++){
  await file.setInputFiles(path.resolve('tests/fixtures/mapping.xlsx'));
  await expect(mapping).toBeVisible();
  for(const [label,column] of [['Дата *','booked'],['Сумма *','value'],['Направление','flow'],['Остаток на конец дня','closing']]){
   await mapping.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name:column,exact:true}).click();
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
 await page.goto('/companies/new');
 await page.getByLabel('Название компании',{exact:true}).fill('Synthetic 1C bank file');
 await page.getByLabel('Вид деятельности',{exact:true}).fill('Tests');
 await page.getByLabel('ИНН',{exact:true}).fill('7707083893');
 await page.getByRole('button',{name:'Создать компанию',exact:true}).click();await expect(page).toHaveURL(/\/sources$/);
 await page.getByRole('button',{name:/^1С Подключение/}).click();
 await page.getByRole('button',{name:'Импортировать файлы из 1С',exact:true}).click();
 await expect(page.getByLabel('Адрес OData 1С',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Перейти к импорту банковской выписки',exact:true}).click();
 const bank=`1CClientBankExchange
ВерсияФормата=1.03
Кодировка=UTF-8
ДатаНачала=24.10.2026
ДатаКонца=24.10.2026
РасчСчет=40702810000000000001
СекцияРасчСчет
ДатаНачала=24.10.2026
ДатаКонца=24.10.2026
РасчСчет=40702810000000000001
НачальныйОстаток=10000.00
КонечныйОстаток=9000.00
КонецРасчСчет
СекцияДокумент=Платежное поручение
Номер=SYNTHETIC-1
Дата=24.10.2026
Сумма=1000.00
ПлательщикСчет=40702810000000000001
ПлательщикИНН=7707083893
Плательщик1=Synthetic test workspace
ПолучательСчет=40702810000000000099
ПолучательИНН=6164138513
Получатель1=Synthetic supplier
ДатаСписано=24.10.2026
НазначениеПлатежа=SYNTHETIC BANK FILE
КонецДокумента
КонецФайла
`;
 for(let run=0;run<2;run++){
  await file.setInputFiles({name:'synthetic-bank.1c',mimeType:'text/plain',buffer:Buffer.from(bank)});
  const report=page.locator('section').filter({has:page.getByRole('heading',{name:'Результат импорта',exact:true})});
  await expect(report).toContainText(`Добавлено: ${run===0?'1':'0'}`,{timeout:60000});
  if(run===1)await expect(report).toContainText('Дубли: 1');
 }
 const finalProfile=await request.get(`${api}/v1/me`,{headers});const bankCID=(await finalProfile.json()).companies.find(c=>c.name==='Synthetic 1C bank file').id;
 const bankOperations=await request.get(`${api}/v1/companies/${bankCID}/operations`,{headers});expect((await bankOperations.json()).items).toHaveLength(1);
 const bankDashboard=await request.get(`${api}/v1/companies/${bankCID}/dashboard`,{headers});expect((await bankDashboard.json()).balance_now).toBe(9000);
});

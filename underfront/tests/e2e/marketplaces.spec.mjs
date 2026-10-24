import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

test('isolated sandbox: WB/Ozon financial reports, duplicate sync and secret masking', async ({ page, request }) => {
  test.skip(process.env.E2E_INTEGRATION_SANDBOX !== '1', 'Run only against explicitly isolated sandbox stack.');
  const api = process.env.E2E_API_URL;
  const password = 'E2e!A1b2C3d4'; const email = `sandbox-${randomUUID()}@example.invalid`;
  const registration = await request.post(`${api}/v1/auth/register`, { data: { email, password, consent_pd: true } });
  expect(registration.status()).toBe(201);
  const headers = { Authorization: `Bearer ${(await registration.json()).access_token}` };
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Электронная почта' }).fill(email);
  await page.getByRole('textbox', { name: 'Пароль', exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/companies\/new$/);
  await page.getByRole('textbox', { name: 'Название компании' }).fill('Synthetic marketplace workspace');
  await page.getByRole('textbox', { name: 'Вид деятельности' }).fill('Tests');
  await page.getByRole('button', { name: 'Создать компанию', exact: true }).click();
  await expect(page).toHaveURL(/\/sources$/);
  await expect(page.getByRole('status').filter({ hasText: 'ДЕМОНСТРАЦИЯ / MOCK' })).toBeVisible();
  const workspace = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Маркетплейсы · отчёты продавца' }) });
  for (const provider of ['Wildberries', 'Ozon']) {
    await workspace.getByRole('button', { name: 'Маркетплейс', exact: true }).click();
    await page.getByRole('option', { name: provider, exact: true }).click();
    if (provider === 'Ozon') await workspace.getByRole('textbox', { name: 'Client ID Ozon' }).fill('sandbox-client');
    await workspace.getByLabel('Ключ продавца маркетплейса', { exact: true }).fill('sandbox-key');
    await workspace.getByLabel('Отчёт с даты', { exact: true }).fill('2026-10-01');
    await workspace.getByLabel('Отчёт по дату', { exact: true }).fill('2026-10-07');
    await workspace.getByRole('button', { name: 'Подключить и загрузить отчёт' }).click();
    await expect(workspace.getByRole('status')).toContainText('Отчёт сохранён', { timeout: 60_000 });
    await expect(workspace.getByLabel('Ключ продавца маркетплейса', { exact: true })).toHaveValue('');
  }
  await expect(workspace.getByRole('article')).toHaveCount(4);
  const profile = await request.get(`${api}/v1/me`, { headers }); const cid = (await profile.json()).companies[0].id;
  const sources = await request.get(`${api}/v1/companies/${cid}/sources`, { headers }); const sourceData = await sources.json();
  expect(JSON.stringify(sourceData)).not.toContain('sandbox-key');
  for (const source of sourceData) {
    expect(source.data_mode).toBe('mock');
    const jobResponse = await request.post(`${api}/v1/sources/${source.id}/sync`, { headers }); expect(jobResponse.status()).toBe(202);
    const job = await jobResponse.json();
    await expect.poll(async () => (await (await request.get(`${api}/v1/jobs/${job.id}`, { headers })).json()).status).toBe('done');
  }
  const reports = await request.get(`${api}/v1/companies/${cid}/marketplace-reports`, { headers }); const data = await reports.json(); expect(data).toHaveLength(4);
  for (const row of data) { expect(row.data_mode).toBe('mock'); expect(row.forecast_eligible).toBe(false); expect(row.bank_fact).toBe(false); }
  const operations = await request.get(`${api}/v1/companies/${cid}/operations`, { headers }); expect((await operations.json()).items).toHaveLength(0);
  await page.reload(); await expect(workspace.getByRole('article')).toHaveCount(4);
  const wbSource=page.getByRole('article').filter({has:page.getByRole('heading',{name:'Wildberries · отчёты продавца',exact:true})});
  await wbSource.getByRole('button',{name:'Доступ и параметры',exact:true}).click();
  const credentials=page.getByRole('dialog');
  await credentials.getByLabel('Новый ключ доступа',{exact:true}).fill('sandbox-key');
  await credentials.getByRole('button',{name:'Сохранить параметры',exact:true}).click();
  await expect(credentials).toHaveCount(0);
  await expect(wbSource).toContainText('Ожидает проверки');
  await wbSource.getByRole('button',{name:'Проверить',exact:true}).click();
  await expect(wbSource).toContainText('Готово');
  const shots = process.env.E2E_SCREENSHOTS_DIR || path.resolve('../docs/e2e-v2-screenshots'); mkdirSync(shots, { recursive: true });
  await workspace.screenshot({ path: path.join(shots, 'marketplace-sandbox-reports.png') });
  const sheet = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Google Sheets · предпросмотр и импорт', exact: true }) });
  await sheet.getByLabel('ID таблицы Google Sheets', { exact: true }).fill('synthetic-sheet');
  await sheet.getByLabel('Ключ доступа Google Sheets', { exact: true }).fill('sandbox-key');
  await sheet.getByRole('button', { name: 'Сохранить доступ и показать столбцы', exact: true }).click();
  await expect(sheet.getByRole('heading', { name: 'Столбцы Google Sheets · проверьте сопоставление' })).toBeVisible();
  await expect(sheet).toContainText('Sandbox customer');
  await expect(sheet.getByLabel('Ключ доступа Google Sheets', { exact: true })).toHaveValue('');
  await sheet.getByRole('button', { name: 'Подтвердить столбцы и импортировать таблицу' }).click();
  await expect(sheet.getByRole('status')).toContainText('Новых операций: 1', { timeout: 60_000 });
  const afterSheet = await request.get(`${api}/v1/companies/${cid}/operations`, { headers });
  expect((await afterSheet.json()).items).toHaveLength(1);
  await page.reload();
  const persisted = await request.get(`${api}/v1/companies/${cid}/operations`, { headers });
  expect((await persisted.json()).items).toHaveLength(1);
  await sheet.screenshot({ path: path.join(shots, 'sheets-sandbox-import.png') });
});

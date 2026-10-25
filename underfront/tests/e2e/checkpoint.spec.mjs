import { test, expect } from '@playwright/test';
import { randomUUID, createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { strFromU8, unzipSync } from 'fflate';

const api = process.env.E2E_API_URL || 'http://localhost:8080';
const dayAt = offset => { const day = new Date(); day.setUTCDate(day.getUTCDate() + offset); return day.toISOString().slice(0, 10); };
function csv(company = 'C001') {
  let result = 'company_id;operation_id;operation_date;amount;direction;counterparty_name;payment_purpose;balance_eod\n';
  for (let i = 90; i >= 1; i--) {
    result += `${company};in-${i};${dayAt(-i)};1000;Поступление;Покупатель;Оплата услуг;100000\n`;
    result += `${company};out-${i};${dayAt(-i)};1000;Списание;Поставщик;Оплата материалов;100000\n`;
  }
  return result;
}
async function workspace(page, request) {
  const email = `checkpoint-${randomUUID()}@example.invalid`, password = 'Synthetic-checkpoint-2026!';
  const registered = await request.post(api + '/v1/auth/register', { data: { email, password, consent_pd: true } });
  expect(registered.status()).toBe(201);
  const headers = { Authorization: `Bearer ${(await registered.json()).access_token}` };
  const response = await request.post(api + '/v1/companies', { headers, data: { name: 'Existing checkpoint workspace', legal_form: 'ООО', industry: 'Tests' } });
  expect(response.status()).toBe(201);
  const company = await response.json();
  await page.goto('/login');
  await page.getByLabel('Электронная почта', { exact: true }).fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await page.goto('/methodology');
  await expect(page.getByRole('heading', { name: 'Проверка контрольного датасета', exact: true })).toBeVisible();
  return { company, headers, async report() {
    const response = await request.get(`${api}/v1/companies/${company.id}/state`, { headers }); expect(response.status()).toBe(200);
    return (await response.json()).data.checkpoint_reports?.[0];
  } };
}

test('combined CSV holdout uses one company, withholds future rows, exports evidence and restores saved reports', async ({ page, request }) => {
  const w = await workspace(page, request);
  const combined = csv('C001') + csv('C002').split('\n').slice(1).join('\n');
  await page.getByLabel('Контрольный датасет CSV', { exact: true }).setInputFiles({ name: 'all_operations.csv', mimeType: 'text/csv', buffer: Buffer.from(combined) });
  await expect(page.getByText('Найдено компаний: 2.', { exact: false })).toBeVisible();
  await page.getByRole('combobox', { name: 'Компания из набора', exact: true }).click();
  await page.getByRole('option', { name: 'C002 · C002', exact: true }).click();
  await expect(page.getByLabel('Последний день истории для модели', { exact: true })).toHaveValue(dayAt(-31));
  await page.getByRole('button', { name: 'Запустить проверку', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Результат расчёта', exact: true })).toBeVisible({ timeout: 120000 });
  await expect(page.getByRole('table', { name: 'Матрица ошибок кассового разрыва', exact: true })).toContainText('TN · 30');
  const report = await w.report();
  expect(report.dataset_company).toBe('C002'); expect(report.mode).toBe('holdout'); expect(report.cutoff).toBe(dayAt(-31));
  expect(report.input.training_rows).toBe(120); expect(report.input.withheld_rows).toBe(60); expect(report.metrics.samples).toBe(30);
  const original = await request.get(`${api}/v1/companies/${w.company.id}/operations`, { headers: w.headers });
  expect((await original.json()).total).toBe(0);
  const imported = await request.get(`${api}/v1/companies/${report.company_id}/operations?limit=200`, { headers: w.headers });
  const operations = await imported.json(); expect(operations.total).toBe(120); expect(operations.items.every(op => op.date <= report.cutoff)).toBe(true);
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать результаты ZIP', exact: true }).click();
  const download = await downloadEvent;
  const files = unzipSync(await readFile(await download.path()));
  const history = strFromU8(files['history.csv']);
  expect(history).not.toContain(dayAt(-1)); expect(history).toContain(dayAt(-31));
  expect(strFromU8(files['withheld.csv'])).toContain(dayAt(-1));
  expect(createHash('sha256').update(history).digest('hex')).toBe(report.input.training_sha256);
  expect(JSON.parse(strFromU8(files['protocol.json'])).future_rows_excluded_from_upload).toBe(true);
  await page.reload();
  await page.getByRole('button', { name: /^C002 · / }).click();
  await expect(page.getByRole('heading', { name: 'Результат расчёта', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Как мы считаем', exact: true })).toHaveCount(0);
});

test('prediction-only CSV never fabricates holdout metrics or a confusion matrix', async ({ page, request }) => {
  const w = await workspace(page, request);
  await page.getByLabel('Контрольный датасет CSV', { exact: true }).setInputFiles({ name: 'statement.csv', mimeType: 'text/csv', buffer: Buffer.from(csv()) });
  await expect(page.getByRole('button', { name: 'Запустить проверку', exact: true })).toBeEnabled();
  await page.getByRole('combobox', { name: 'Режим проверки', exact: true }).click();
  await page.getByRole('option', { name: 'Построить прогноз после конца файла', exact: true }).click();
  await page.getByRole('combobox', { name: 'Горизонт, дней', exact: true }).click();
  await page.getByRole('option', { name: '7', exact: true }).click();
  await page.getByRole('button', { name: 'Запустить проверку', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Результат расчёта', exact: true })).toBeVisible({ timeout: 120000 });
  const report = await w.report();
  expect(report.cutoff).toBe(dayAt(-1)); expect(report.horizon).toBe(7); expect(report.input.withheld_rows).toBe(0);
  expect(report.metrics.samples).toBe(0); expect(report.metrics.mae).toBeNull(); expect(report.metrics.mse).toBeNull(); expect(report.metrics.confusion).toBeNull();
  await expect(page.getByText('Матрица ошибок недоступна без сопоставимого факта.', { exact: true })).toBeVisible();
});

test('invalid control file stops before creating or importing into a company', async ({ page, request }) => {
  const w = await workspace(page, request);
  await page.getByLabel('Контрольный датасет CSV', { exact: true }).setInputFiles({ name: 'bad.csv', mimeType: 'text/csv', buffer: Buffer.from('date;amount;direction\n2026-01-01;10;in\n') });
  await expect(page.getByRole('alert').filter({ hasText: 'Нет столбца' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Запустить проверку', exact: true })).toHaveCount(0);
  const profile = await request.get(api + '/v1/me', { headers: w.headers });
  expect((await profile.json()).companies).toHaveLength(1);
});

test('failed API execution remains a failed run with downloadable observations', async ({ page, request }) => {
  const w = await workspace(page, request);
  await page.route('**/v1/companies', route => route.request().method() === 'POST'
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 'test_unavailable', message: 'Тестовая недоступность сервера' }) })
    : route.continue());
  await page.getByLabel('Контрольный датасет CSV', { exact: true }).setInputFiles({ name: 'statement.csv', mimeType: 'text/csv', buffer: Buffer.from(csv()) });
  await expect(page.getByRole('button', { name: 'Запустить проверку', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Запустить проверку', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Тестовая недоступность' })).toBeVisible();
  await expect(page.getByText('Проверка остановлена:', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Результат расчёта', exact: true })).toHaveCount(0);
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать логи JSONL', exact: true }).click();
  const download = await downloadEvent;
  const text = (await readFile(await download.path())).toString();
  expect(JSON.parse(text.trim().split('\n').at(-1)).event).toBe('run_failed');
  expect(text).not.toContain('Authorization'); expect(text).not.toContain('access_token');
  expect(await w.report()).toBeUndefined();
});

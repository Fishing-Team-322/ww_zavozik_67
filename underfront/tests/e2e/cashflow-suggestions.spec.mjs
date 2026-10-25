import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

const api = process.env.E2E_API_URL || 'http://localhost:8080';
const dateAt = offset => { const date = new Date(); date.setUTCDate(date.getUTCDate() + offset); return date.toISOString().slice(0, 10); };

test('cashflow suggestions show calculated effects and apply a receipt plan after confirmation', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // An isolated API can serve the existing dev frontend without replacing
  // the user's current backend or changing its data.
  if (process.env.E2E_API_URL) {
    await page.route('**/v1/**', async route => {
      const url = new URL(route.request().url());
      const response = await route.fetch({ url: `${api}${url.pathname}${url.search}`, headers: { ...route.request().headers(), origin: process.env.E2E_ALLOWED_ORIGIN || process.env.E2E_BASE_URL || "http://localhost:3000" } });
      await route.fulfill({ response });
    });
  }
  const email = `cashflow-${randomUUID()}@example.invalid`, password = 'Synthetic-cashflow-2026!';
  const registration = await request.post(`${api}/v1/auth/register`, { data: { email, password, consent_pd: true } });
  expect(registration.status()).toBe(201);
  const headers = { Authorization: `Bearer ${(await registration.json()).access_token}` };
  const company = await request.post(`${api}/v1/companies`, { headers, data: { name: 'Демо подсказок по денежному потоку', legal_form: 'ООО', industry: 'services' } });
  expect(company.status()).toBe(201);
  const cid = (await company.json()).id, base = `${api}/v1/companies/${cid}`;
  let csv = 'operation_date;amount;direction;counterparty_name;payment_purpose;balance_eod;operation_id\n';
  for (let i = 90; i >= 1; i--) {
    csv += `${dateAt(-i)};1000;in;Клиент ${i};Оплата услуг;100000;in-${i}\n${dateAt(-i)};1000;out;Поставщик ${i};Оплата материалов;100000;out-${i}\n`;
  }
  const upload = await request.post(`${base}/uploads`, { headers, multipart: { file: { name: 'cashflow.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) } } });
  expect(upload.status()).toBe(202);
  const job = (await upload.json()).id;
  await expect.poll(async () => (await (await request.get(`${api}/v1/jobs/${job}`, { headers })).json()).status, { timeout: 90000 }).toBe('done');
  const expense = await request.post(`${base}/events`, { headers, data: { date: dateAt(2), amount: 200000, direction: 'out', title: 'Оборудование', category: 'supplier', additional: true } });
  expect(expense.status()).toBe(201);
  const invoice = await request.post(`${base}/invoices`, { headers, data: { number: 'CLIENT-CASHFLOW', direction: 'issued', amount: 150000, issued_at: dateAt(-1), due_at: dateAt(10), counterparty_name: 'Клиент по договору', additional: true } });
  expect(invoice.status()).toBe(201);
  const iid = (await invoice.json()).id;
  await page.goto('/login');
  await page.getByLabel('Электронная почта', { exact: true }).fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/overview$/);
  const suggestions = page.getByRole('region', { name: 'Подсказки по денежному потоку' });
  await expect(suggestions.getByText('Запросить более раннюю оплату', { exact: true })).toBeVisible();
  await expect(suggestions.getByLabel('Расчёт эффекта').first()).toContainText('Уменьшение нехватки:');
  await suggestions.getByRole('link', { name: 'Сравнить и выбрать действия' }).click();
  const receipt = page.getByRole('article').filter({ hasText: 'Запросить более раннюю оплату' });
  await expect(receipt).toContainText('CLIENT-CASHFLOW');
  await expect(receipt).toContainText('Требуется подтверждение клиента');
  await expect(receipt).toContainText('По расчёту разрыв не ожидается');
  await receipt.getByRole('checkbox').focus();
  await receipt.getByRole('checkbox').press('Space');
  await page.getByRole('button', { name: 'Посмотреть эффект', exact: true }).click();
  await expect(page.getByText('Нехватка устранена', { exact: true })).toBeVisible();
  const before = await (await request.get(`${base}/invoices`, { headers })).json();
  expect(before.find(item => item.id === iid).expected_pay_at).toBe(dateAt(10));
  await receipt.getByText('Черновик сообщения', { exact: true }).click();
  await expect(receipt).toContainText('Просим подтвердить возможность');
  const shot = process.env.E2E_SCREENSHOTS_DIR || path.resolve('test-results');
  await page.screenshot({ path: path.join(shot, 'cashflow-suggestions.png'), fullPage: true });
  await receipt.getByRole('button', { name: 'Применить к плану', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Применить действие к плану?' });
  await expect(dialog).toContainText('Требуется подтверждение клиента');
  await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(async () => (await (await request.get(`${base}/invoices`, { headers })).json()).find(item => item.id === iid).expected_pay_at).toBe(dateAt(2));
  expect(errors).toEqual([]);
});

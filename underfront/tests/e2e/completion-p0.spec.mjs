import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

const api = process.env.E2E_API_URL || 'http://localhost:8080';
const screenshots = process.env.E2E_SCREENSHOTS_DIR || path.resolve('test-results/screenshots');
const password = 'E2e!A1b2C3d4';

test('self-service, legacy query links, checksum, isolated same-INN workspaces and balance provenance', async ({ page, request }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const register = async () => {
    const email = `v2-${randomUUID()}@example.invalid`;
    const response = await request.post(`${api}/v1/auth/register`, { data: { email, password, consent_pd: true } });
    expect(response.status()).toBe(201);
    return { email, token: (await response.json()).access_token };
  };
  const user = await register();
  const headers = { Authorization: `Bearer ${user.token}` };
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Электронная почта' }).fill(user.email);
  await page.getByRole('textbox', { name: 'Пароль', exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/companies\/new$/);
  await expect(page.getByText(/без согласования с администратором/)).toBeVisible();
  await page.getByRole('textbox', { name: 'ИНН', exact: true }).fill('6164138512');
  await page.getByRole('textbox', { name: 'Название компании' }).fill('V2 isolated workspace');
  await page.getByRole('textbox', { name: 'Вид деятельности' }).fill('Tests');
  await page.getByRole('button', { name: 'Создать компанию', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: /контрольная цифра/ })).toBeVisible();
  await page.getByRole('textbox', { name: 'ИНН', exact: true }).fill('6164138513');
  await page.getByRole('button', { name: 'Создать компанию', exact: true }).click();
  await expect(page).toHaveURL(/\/sources$/);
  const profile = await request.get(`${api}/v1/me`, { headers });
  const company = (await profile.json()).companies[0];
  const other = await register();
  const second = await request.post(`${api}/v1/companies`, { headers: { Authorization: `Bearer ${other.token}` }, data: { name: 'V2 independent', legal_form: 'ООО', industry: 'Tests', inn: '6164138513' } });
  expect(second.status()).toBe(201);
  expect((await second.json()).id).not.toBe(company.id);
  expect((await request.get(`${api}/v1/companies/${company.id}`, { headers: { Authorization: `Bearer ${other.token}` } })).status()).toBe(404);
  const base = `/v1/companies/${company.id}`;
  for (const [suffix, expected] of [[`/operations`, 200], [`/operations?counterparty_id=`, 200], [`/operations?counterparty_id=${randomUUID()}`, 200], [`/operations?counterparty_id=bad`, 400], ['/alerts', 200], ['/alerts?unread=', 200], ['/alerts?unread=true', 200], ['/alerts?unread=false', 200], ['/alerts?unread=bad', 400]]) {
    // Exercise the real Next proxy, not just the direct API listener.
    const response = await page.request.get(base + suffix, { headers });
    expect(response.status(), suffix).toBe(expected);
    expect(await response.text()).not.toMatch(/unmarshaling|strconv|invalid UUID length/);
  }
  for (const route of ['/transactions?counterparty_id=', '/notifications?unread=']) {
    await page.goto(route);
    await expect(page.locator('main').getByRole('heading').first()).toBeVisible();
    await expect(page.getByText('Загружаем данные…', { exact: true })).not.toBeVisible();
    await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  }
  mkdirSync(screenshots, { recursive: true });
  await page.screenshot({ path: path.join(screenshots, 'p0-notifications.png') });
  for (const [name, balance] of [['unknown', null], ['zero', '0.00'], ['measured', '123456.78']]) {
    await page.goto('/companies/new');
    await page.getByRole('textbox', { name: 'Название компании' }).fill(`V2 balance ${name}`);
    await page.getByRole('textbox', { name: 'Вид деятельности' }).fill('Tests');
    await page.getByRole('button', { name: 'Создать компанию', exact: true }).click();
    await expect(page).toHaveURL(/\/sources$/);
    const profile = await request.get(`${api}/v1/me`, { headers });
    const cid = (await profile.json()).companies.find(c => c.name === `V2 balance ${name}`).id;
    const today = new Date().toISOString().slice(0, 10);
    const csv = `date,amount,direction,counterparty_name,purpose${balance === null ? '' : ',balance_eod'}\n${today},100,in,Fixture,Balance test${balance === null ? '' : ',' + balance}\n`;
    await page.getByRole('button',{name:/^Банковская выписка/}).click();
    await page.locator('input[type="file"][accept=".csv,.xlsx,.txt,.1c"]').setInputFiles({ name: `${name}.csv`, mimeType: 'text/csv', buffer: Buffer.from(csv) });
    await expect(page.locator('section').filter({ has: page.getByRole('heading', { name: 'Результат импорта' }) })).toContainText('Добавлено: 1', { timeout: 60_000 });
    const dashboard = await request.get(`${api}/v1/companies/${cid}/dashboard`, { headers });
    expect(dashboard.status()).toBe(200);
    expect((await dashboard.json()).balance_now).toBe(balance === null ? null : Number(balance));
    await page.goto('/overview');
    if (balance === null) await expect(page.getByRole('heading', { name: 'Для прогноза нужны операции и остаток на счёте' })).toBeVisible();
    else await expect(page.getByRole('heading', { name: /Финансовый прогноз/ })).toBeVisible();
    await page.screenshot({ path: path.join(screenshots, `p0-balance-${name}.png`) });
    await page.reload();
    await expect(page.locator('main').getByRole('heading').first()).toBeVisible();
  }
  expect(errors).toEqual([]);
});

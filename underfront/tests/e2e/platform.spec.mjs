import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const apiOrigin = process.env.E2E_API_URL || 'http://localhost:8080';
const password = 'E2e!A1b2C3d4'; // Synthetic account in the isolated E2E database only.
const screenshots = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../docs/e2e-screenshots');

async function register(request) {
  const email = `e2e-${randomUUID()}@example.invalid`;
  const response = await request.post(`${apiOrigin}/v1/auth/register`, {
    data: { email, password, consent_pd: true },
  });
  expect(response.status()).toBe(201);
  return { email, token: (await response.json()).access_token };
}

async function createCompany(page, name, inn = '') {
  await page.goto('/companies/new');
  await expect(page.getByRole('heading', { name: 'Новая компания' })).toBeVisible();
  if (inn) await page.getByRole('textbox', { name: 'ИНН', exact: true }).fill(inn);
  await page.getByRole('textbox', { name: 'Название компании' }).fill(name);
  await page.getByRole('textbox', { name: 'Вид деятельности' }).fill('Тестирование');
  await page.getByRole('button', { name: 'Создать компанию', exact: true }).click();
  await expect(page).toHaveURL(/\/sources$/);
}

async function login(page, email) {
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Электронная почта' }).fill(email);
  await page.getByRole('textbox', { name: 'Пароль' }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/companies\/new$|\/overview$/);
}

async function navigate(page, route) {
  const groups = { '/overview': 'Workspace', '/transactions': 'Workspace', '/forecast': 'Analytics', '/scenarios': 'Analytics', '/risks': 'Analytics', '/calendar': 'Planning', '/sources': 'Planning' };
  const link = page.locator(`a[href="${route}"]`).first();
  if (!await link.isVisible()) await page.getByRole('button', { name: groups[route], exact: true }).click();
  await link.click();
  await expect(page).toHaveURL(new RegExp(`${route}$`));
}

test('public authentication routes have explicit states', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const [route, heading] of [['/login', 'Вход'], ['/register', 'Регистрация'], ['/forgot-password', 'Восстановление пароля'], ['/privacy', 'Обработка персональных данных']]) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  await page.goto('/reset-password');
  await expect(page.getByRole('alert').filter({ hasText: 'В ссылке нет токена' })).toBeVisible();
  await page.goto('/auth/callback');
  await expect(page.getByRole('link', { name: 'Вернуться ко входу' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('anonymous data is protected and an unavailable source fails clearly', async ({ page, request }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  const anonymous = await request.get(`${apiOrigin}/v1/companies/${randomUUID()}/operations`);
  expect(anonymous.status()).toBe(401);
  await page.goto('/sources');
  await expect(page).toHaveURL(/\/login(?:\?|$)/);

  const user = await register(request);
  await login(page, user.email);
  await createCompany(page, 'E2E empty company');
  await expect(page.getByRole('heading', { name: 'Источники данных' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Адрес OData 1С' }).fill('https://example.invalid/odata/');
  await page.getByRole('textbox', { name: 'ИНН компании' }).fill('7725895601');
  await page.getByRole('textbox', { name: 'Расчётный счёт компании' }).fill('40802810999900003157');
  await page.getByRole('button', { name: 'Подключить и синхронизировать' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /разрешён|подобрать|недоступ|адрес/i })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Источники данных' })).toBeVisible();
  mkdirSync(screenshots, { recursive: true });
  await page.screenshot({ path: path.join(screenshots, 'sources-empty-desktop.png'), mask: [page.getByRole('textbox', { name: 'ИНН компании' })] });
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByRole('heading', { name: 'Источники данных' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: path.join(screenshots, 'sources-empty-mobile.png'), mask: [page.getByRole('textbox', { name: 'ИНН компании' })] });
  const ownProfile = await request.get(`${apiOrigin}/v1/me`, { headers: { Authorization: `Bearer ${user.token}` } });
  expect(ownProfile.status()).toBe(200);
  const companyId = (await ownProfile.json()).companies[0].id;
  const other = await register(request);
  const isolated = await request.get(`${apiOrigin}/v1/companies/${companyId}/operations`, {
    headers: { Authorization: `Bearer ${other.token}` },
  });
  expect([403, 404]).toContain(isolated.status());
  await page.route('**/v1/companies/*/sources', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ code: 'test_unavailable', message: 'E2E: сервер временно недоступен' }) }));
  await page.reload();
  await expect(page.getByRole('alert').filter({ hasText: 'E2E: сервер временно недоступен' })).toBeVisible();
  await page.unroute('**/v1/companies/*/sources');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Источники данных' })).toBeVisible();
  expect(pageErrors).toEqual([]);
});

test('live educational 1C imports once and keeps undated invoices out of calendar', async ({ page, request }) => {
  test.skip(!process.env.LIVE_ONEC_URL, 'Set LIVE_ONEC_URL to opt in to the local educational 1C clone.');
  const pageErrors = [];
  const http500 = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response', response => { if (response.status() >= 500 && response.status() !== 503) http500.push(response.url()); });
  const user = await register(request);
  await login(page, user.email);
  await createCompany(page, 'E2E live 1C clone', process.env.LIVE_ONEC_INN);
  await page.getByRole('textbox', { name: 'Адрес OData 1С' }).fill(process.env.LIVE_ONEC_URL);
  await page.getByRole('textbox', { name: 'Расчётный счёт компании' }).fill(process.env.LIVE_ONEC_ACCOUNT);
  await page.getByRole('button', { name: 'Подключить и синхронизировать' }).click();
  await expect(page.getByRole('status').filter({ hasText: /Синхронизация завершена/ })).toContainText('Новых операций: 15', { timeout: 120_000 });
  await expect(page.getByRole('heading', { name: 'Счета из 1С' })).toBeVisible();
  await expect(page.locator('section').filter({ has: page.getByRole('heading', { name: 'Счета из 1С' }) })).toContainText('Срок неизвестен');
  if (process.env.LIVE_ONEC_EXPECT_PARTIAL === '1') {
    const profile = await request.get(`${apiOrigin}/v1/me`, { headers: { Authorization: `Bearer ${user.token}` } });
    const companyId = (await profile.json()).companies[0].id;
    const response = await request.get(`${apiOrigin}/v1/companies/${companyId}/events`, { headers: { Authorization: `Bearer ${user.token}` } });
    expect(response.status()).toBe(200);
    const events = await response.json();
    expect(events).toHaveLength(7);
    const partial = events.find(event => event.total_kopecks === 35_000_000);
    expect(partial.paid_kopecks).toBe(10_000_000);
    expect(partial.remaining_kopecks).toBe(25_000_000);
    expect(partial.payment_status).toBe('partially_paid');
    const invoices = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Счета из 1С' }) });
    await expect(invoices).toContainText(/250\s000,00/);
    mkdirSync(screenshots, { recursive: true });
    await invoices.screenshot({ path: path.join(screenshots, 'onec-partial-obligations.png') });
  }
  await page.getByRole('article').filter({ hasText: 'Операций: 15' }).getByRole('button', { name: 'Синхронизировать', exact: true }).click();
  await expect(page.locator('tr:has(td:nth-child(3):text-is("0")):has(td:nth-child(4):text-is("15"))')).toBeVisible({ timeout: 120_000 });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Счета из 1С' })).toBeVisible();
  mkdirSync(screenshots, { recursive: true });
  await page.screenshot({ path: path.join(screenshots, 'onec-live-redacted.png'), mask: [page.getByRole('textbox', { name: 'ИНН компании' }), page.locator('section').filter({ has: page.getByRole('heading', { name: 'Счета из 1С' }) }), page.getByRole('table')] });
  await navigate(page, '/overview');
  await expect(page.getByRole('heading', { name: 'Для прогноза нужны операции и остаток на счёте' })).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, 'overview-missing-balance.png') });
  await navigate(page, '/transactions');
  await expect(page.getByRole('heading', { name: 'История операций' })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'CODEX E2E частичная оплата' })).toBeVisible();
  await expect(page.getByRole('table').getByRole('row').nth(1)).toContainText('24.10.2026');
  await navigate(page, '/calendar');
  await expect(page.getByRole('heading', { name: 'Платёжный календарь' })).toBeVisible();
  await expect(page.getByRole('table')).not.toContainText('Счёт №0000-000006');
  expect(pageErrors).toEqual([]);
  expect(http500).toEqual([]);
});

test('synthetic CSV drives dashboard, forecast and a persistent manual event', async ({ page, request }) => {
  const http500 = [];
  page.on('response', response => { if (response.status() === 500) http500.push(response.url()); });
  const user = await register(request);
  await login(page, user.email);
  await createCompany(page, 'E2E synthetic cashflow');
  const today = new Date();
  let csv = 'date,amount,direction,counterparty_name,counterparty_inn,purpose,balance_eod\n';
  for (let i = 119; i >= 0; i--) {
    const date = new Date(today);
    date.setUTCDate(date.getUTCDate() - i);
    const day = date.toISOString().slice(0, 10);
    const balance = 100_000 + (119 - i) * 100;
    csv += `${day},1000,in,E2E customer,,Synthetic sales,${balance}\n`;
    csv += `${day},900,out,E2E supplier,,Synthetic supplies,${balance}\n`;
  }
  let failJobPoll = true;
  await page.route('**/v1/jobs/*', route => {
    if (failJobPoll) { failJobPoll = false; return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'E2E polling outage' }) }); }
    return route.continue();
  });
  await page.locator('input[type="file"]').setInputFiles({ name: 'synthetic-statement.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await expect(page.getByRole('alert').filter({ hasText: 'Проверка задания приостановлена' })).toBeVisible();
  await page.getByRole('button', { name: 'Повторить проверку задания' }).click();
  const report = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Результат импорта' }) });
  await expect(report).toContainText('240', { timeout: 60_000 });

  await navigate(page, '/overview');
  await expect(page.getByRole('heading', { name: /Финансовый прогноз/ })).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: path.join(screenshots, 'dashboard-synthetic.png') });
  const [dashboardResponse] = await Promise.all([
    page.waitForResponse(response => response.url().includes('/dashboard?horizon=60')),
    page.getByRole('tab', { name: '60 дн.', exact: true }).click(),
  ]);
  expect(dashboardResponse.status()).toBe(200);
  const dashboard = await dashboardResponse.json();
  expect(dashboard.forecast.points).toHaveLength(60);
  expect(dashboard.forecast.warnings).not.toContain('ml_service_fallback');
  await navigate(page, '/forecast');
  await expect(page.getByRole('heading', { name: 'Денежный остаток' })).toBeVisible();
  await page.getByRole('button', { name: 'Горизонт прогноза' }).click();
  const [forecastResponse] = await Promise.all([
    page.waitForResponse(response => response.url().includes('/forecast?') && new URL(response.url()).searchParams.get('horizon') === '60'),
    page.getByRole('option', { name: '60 дней', exact: true }).click(),
  ]);
  expect(forecastResponse.status()).toBe(200);
  expect((await forecastResponse.json()).points).toHaveLength(60);
  await expect(page.getByRole('button', { name: 'Горизонт прогноза' })).toContainText('60 дней');
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0);

  await navigate(page, '/calendar');
  const tomorrow = new Date(today);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  const eventDate = tomorrow.toISOString().slice(0, 10);
  await page.getByRole('textbox', { name: 'Название платежа' }).fill('E2E manual payment');
  await page.getByRole('textbox', { name: 'Дата платежа' }).fill(eventDate);
  await page.getByRole('spinbutton', { name: 'Сумма, ₽' }).fill('200000');
  await page.getByRole('button', { name: 'Сохранить событие' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Событие сохранено' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Месяц календаря' }).fill(eventDate.slice(0, 7));
  await expect(page.getByRole('row').filter({ hasText: 'E2E manual payment' })).toBeVisible();
  await page.reload();
  await page.getByRole('textbox', { name: 'Месяц календаря' }).fill(eventDate.slice(0, 7));
  await expect(page.getByRole('row').filter({ hasText: 'E2E manual payment' })).toBeVisible();
  for (const [route, heading] of [['/transactions', 'История операций'], ['/scenarios', 'Базовый и негативный прогноз']]) {
    await navigate(page, route);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
  }
  const [scenarioResponse] = await Promise.all([
    page.waitForResponse(response => response.url().includes('/scenarios/preview') && response.request().method() === 'POST'),
    page.getByRole('slider', { name: /Внеплановый расход/ }).press('ArrowRight'),
  ]);
  expect(scenarioResponse.status()).toBe(200);
  await page.getByRole('button', { name: 'Сохранить сценарий', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Сценарий сохранён' })).toBeVisible();
  await navigate(page, '/risks');
  await page.getByRole('button', { name: 'Причины и действия' }).first().click();
  await expect(page.getByRole('heading', { name: 'Что влияет на разрыв' })).toBeVisible();
  await expect(page.locator('main')).toContainText('E2E manual payment');
  await page.screenshot({ path: path.join(screenshots, 'risk-synthetic.png') });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  for (const [route, heading] of [['/overview', /Финансовый прогноз/], ['/transactions', 'История операций'], ['/forecast', 'Денежный остаток'], ['/calendar', 'Платёжный календарь'], ['/scenarios', 'Базовый и негативный прогноз']]) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    await expect(page.getByText('Загружаем данные…', { exact: true })).not.toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `mobile overflow: ${route}`).toBe(true);
    if (route === '/calendar') await page.screenshot({ path: path.join(screenshots, 'calendar-mobile-synthetic.png') });
  }
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto('/test');
  await expect(page.getByText(/Демонстрационная симуляция/)).toBeVisible();
  await page.goto('/development/components');
  await expect(page.getByRole('heading', { name: 'Кнопки', exact: true })).toBeVisible();
  expect(http500).toEqual([]);
});

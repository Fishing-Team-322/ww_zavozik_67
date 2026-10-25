import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
test.use({ actionTimeout: 15000 });

test('isolated administrator: all sections, company details, user status and source action ownership', async ({ page, request }) => {
  test.skip(!process.env.E2E_ADMIN_EMAIL || !process.env.E2E_ADMIN_PASSWORD, 'Prepare an administrator in the isolated E2E database.');
  test.setTimeout(180000);
  const api = process.env.E2E_API_URL || 'http://localhost:8080';
  const email = `admin-subject-${randomUUID()}@example.invalid`, password = 'Synthetic-admin-subject-2026!';
  const registration = await request.post(`${api}/v1/auth/register`, { data: { email, password, consent_pd: true } });
  expect(registration.status()).toBe(201);
  const ownerHeaders = { Authorization: `Bearer ${(await registration.json()).access_token}` };
  const name = `Admin audit ${randomUUID()}`;
  const created = await request.post(`${api}/v1/companies`, { headers: ownerHeaders, data: { name, legal_form: 'ООО', industry: 'Tests' } });
  expect(created.status()).toBe(201);
  const cid = (await created.json()).id;
  const source = await request.post(`${api}/v1/companies/${cid}/sources`, { headers: ownerHeaders, data: { kind: 'upload', title: name } });
  expect(source.status()).toBe(201);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/login');
  await page.getByLabel('Электронная почта', { exact: true }).fill(process.env.E2E_ADMIN_EMAIL);
  await page.getByLabel('Пароль', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/admin$/);
  for (const [route, heading] of [['/admin', 'Обзор платформы'], ['/admin/users', 'Пользователи'], ['/admin/companies', 'Компании'], ['/admin/integrations', 'Интеграции'], ['/admin/models', 'Модели прогноза'], ['/admin/classifier', 'Классификатор'], ['/admin/antifraud/signals', 'Сигналы для проверки'], ['/admin/audit', 'Журнал доступа']]) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    await expect(page.getByText('Загружаем данные…', { exact: true })).toHaveCount(0);
    await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  }
  await page.goto('/admin/companies');
  await page.getByLabel('Название или ИНН', { exact: true }).fill(name);
  await page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: 'Открыть', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('heading', { name, exact: true })).toBeVisible();
  await page.getByRole('dialog').press('Escape');
  await page.goto('/admin/integrations');
  await page.getByLabel('Тип источника', { exact: true }).fill('upload');
  await expect(page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: 'Повторить синхронизацию', exact: true })).toBeDisabled();
  await page.goto('/admin/users');
  await page.getByLabel('Почта', { exact: true }).fill(email);
  const row = page.getByRole('row').filter({ hasText: email });
  const dialog = page.getByRole('dialog');
  for (const [status, label, expected] of [['blocked', 'Заблокирован', 401], ['active', 'Активен', 200]]) {
    await row.getByRole('button', { name: 'Открыть', exact: true }).click();
    await dialog.getByRole('combobox', { name: 'Статус', exact: true }).click();
    await page.getByRole('option', { name: label, exact: true }).click();
    await dialog.getByLabel('Причина изменения', { exact: true }).fill(`Disposable E2E ${status}`);
    await dialog.getByRole('button', { name: 'Подтвердить изменение', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(row).toContainText(label);
    const login = await request.post(`${api}/v1/auth/login`, { data: { email, password } });
    expect(login.status()).toBe(expected);
  }
  expect(errors).toEqual([]);
});

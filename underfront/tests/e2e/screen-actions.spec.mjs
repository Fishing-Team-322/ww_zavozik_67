import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

const api = process.env.E2E_API_URL || 'http://localhost:8080';
const password = 'Synthetic-screen-audit-2026!';
test.use({ actionTimeout: 15000 });
const dateAfter = (day, offset) => { const dt = new Date(`${day}T12:00:00Z`); dt.setUTCDate(dt.getUTCDate() + offset); return dt.toISOString().slice(0, 10); };
const today = () => new Date().toISOString().slice(0, 10);

async function workspace(page, request, history = false, historyAsOf = today()) {
  const email = `screens-${randomUUID()}@example.invalid`;
  const registered = await request.post(`${api}/v1/auth/register`, { data: { email, password, consent_pd: true } });
  expect(registered.status()).toBe(201);
  const headers = { Authorization: `Bearer ${(await registered.json()).access_token}` };
  const created = await request.post(`${api}/v1/companies`, { headers, data: { name: 'Disposable screen audit', legal_form: 'ООО', industry: 'Tests' } });
  expect(created.status()).toBe(201);
  const cid = (await created.json()).id, base = `${api}/v1/companies/${cid}`;
  const get = async path => { const response = await request.get(base + path, { headers }); expect(response.status(), path).toBe(200); return response.json(); };
  const post = async (path, data) => { const response = await request.post(base + path, { headers, data }); expect(response.status(), path).toBe(201); return response.json(); };
  if (history) {
    let csv = 'date;amount;direction;counterparty_name;purpose;balance;id\n';
    for (let i = 119; i >= 0; i--) {
      const day = dateAfter(historyAsOf, -i);
      csv += `${day};1000;in;Audit customer;Sales;${100000 + (119-i)*100};audit-in-${i}\n${day};900;out;Audit supplier;Supplies;${100000 + (119-i)*100};audit-out-${i}\n`;
    }
    const uploaded = await request.post(base + '/uploads', { headers, multipart: { file: { name: 'screens.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) } } });
    expect(uploaded.status()).toBe(202);
    const job = (await uploaded.json()).id;
    await expect.poll(async () => (await (await request.get(`${api}/v1/jobs/${job}`, { headers })).json()).status, { timeout: 120000 }).toBe('done');
    await expect.poll(async () => (await get('/updates')).pending_jobs, { timeout: 120000 }).toBe(0);
  }
  await page.goto('/login');
  await page.getByLabel('Электронная почта', { exact: true }).fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page).toHaveURL(/\/overview$/);
  return { cid, base, headers, get, post };
}

async function choose(page, label, option) {
  await page.getByRole('combobox', { name: label, exact: true }).or(page.getByRole('button', { name: label, exact: true })).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

test('header event shortcut opens the editor on overview and on the calendar itself', async ({ page, request }) => {
  const w = await workspace(page, request, true);
  await page.getByRole('button', { name: '+ Событие', exact: true }).click();
  const editor = page.getByRole('dialog');
  await expect(editor.getByRole('heading', { name: 'Новое событие', exact: true })).toBeVisible();
  await editor.getByLabel('Опишите платёж', { exact: true }).fill('Клиент Аудит заплатит 300 тысяч 28 октября 2026');
  await editor.getByRole('button', { name: 'Заполнить по описанию', exact: true }).click();
  await expect(editor.getByLabel('Сумма, ₽', { exact: true })).toHaveValue('300000');
  await editor.getByLabel('Дата', { exact: true }).fill(dateAfter(today(), 2));
  await editor.getByRole('button', { name: 'Посмотреть прогноз до сохранения', exact: true }).click();
  await expect(editor.getByText(/Доступно после изменения:/)).toBeVisible({ timeout: 60000 });
  expect((await w.get('/events')).some(event => event.amount === 300000)).toBe(false);
  await editor.getByRole('button', { name: 'Сохранить событие', exact: true }).click();
  await expect(editor).toHaveCount(0);
  expect((await w.get('/events')).some(event => event.amount === 300000)).toBe(true);
  await page.locator('header').getByRole('button', { name: '+ Событие', exact: true }).click();
  await expect(editor.getByRole('heading', { name: 'Новое событие', exact: true })).toBeVisible();
  await editor.getByRole('button', { name: 'Отмена', exact: true }).click();
});

test('invoice dates follow the due date and contract term edits preserve generated installments', async ({ page, request }) => {
  const w = await workspace(page, request);
  await page.goto('/documents');
  await page.getByRole('button', { name: 'Добавить счёт', exact: true }).click();
  const editor = page.getByRole('dialog');
  await editor.getByLabel('Номер', { exact: true }).fill('AUDIT-DUE');
  await editor.getByLabel('Сумма, ₽', { exact: true }).fill('1000.01');
  const due = dateAfter(today(), 7);
  await editor.getByLabel('Срок оплаты', { exact: true }).fill(due);
  await expect(editor.getByLabel('Ожидаемая дата оплаты', { exact: true })).toHaveValue(due);
  const expectedPayment = dateAfter(due, 1);
  await editor.getByLabel('Ожидаемая дата оплаты', { exact: true }).fill(expectedPayment);
  await editor.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(editor).toHaveCount(0);
  expect((await w.get('/invoices'))[0].expected_pay_at).toBe(expectedPayment);
  const calendarLink = page.getByRole('row').filter({ hasText: 'AUDIT-DUE' }).getByRole('link', { name: 'Календарь', exact: true });
  await expect(calendarLink).toHaveAttribute('href', `/calendar?date=${expectedPayment}`);
  await calendarLink.click();
  await expect(page.getByRole('heading', { name: expectedPayment.split('-').reverse().join('.'), exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /AUDIT-DUE/ })).toBeVisible();
  await page.goto('/documents');
  const contract = await w.post('/contracts', { number: 'AUDIT-TERMS', direction: 'out', total: 1000, prepayment: 200, start_date: due, deferral_days: 14 });
  await page.getByRole('tab', { name: 'Договоры', exact: true }).click();
  await page.getByRole('row').filter({ hasText: 'AUDIT-TERMS' }).getByRole('button', { name: 'Изменить', exact: true }).click();
  await editor.getByLabel('Предоплата, ₽', { exact: true }).fill('300');
  await editor.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(editor).toHaveCount(0);
  const updated = (await w.get('/contracts')).find(row => row.id === contract.id);
  expect(updated.schedule_mode).toBe('terms');
  expect(updated.schedule.map(row => [row.date, row.amount])).toEqual([[due, 300], [dateAfter(due, 14), 700]]);
  await page.reload();
  await page.getByRole('tab', { name: 'Договоры', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'AUDIT-TERMS' })).toContainText('300,00');
  await page.getByRole('button', { name: 'Добавить договор', exact: true }).click();
  await editor.getByLabel('Номер', { exact: true }).fill('AUDIT-NEW-TERMS');
  await editor.getByLabel('Сумма, ₽', { exact: true }).first().fill('2000');
  await editor.getByLabel('Предоплата, ₽', { exact: true }).fill('500');
  await editor.getByLabel('Отсрочка, дней', { exact: true }).fill('10');
  await editor.getByLabel('Дата', { exact: true }).fill(due);
  await editor.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(editor).toHaveCount(0);
  const generated = (await w.get('/contracts')).find(row => row.number === 'AUDIT-NEW-TERMS');
  expect(generated.schedule_mode).toBe('terms');
  expect(generated.schedule.map(row => [row.date, row.amount])).toEqual([[due, 500], [dateAfter(due, 10), 1500]]);
});

test('manual category and counterparty rules persist, filters and XLSX use the same backend data', async ({ page, request }) => {
  const w = await workspace(page, request, true);
  await page.goto('/transactions');
  await page.getByRole('button', { name: /^Изменить категорию операции / }).first().click();
  const editor = page.getByRole('dialog');
  await choose(page, 'Категория', 'Аренда');
  await editor.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.getByText('Указана вручную', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Указана вручную', { exact: true })).toBeVisible();
  const operations = await w.get('/operations?limit=5');
  expect(operations.items.some(row => row.category === 'rent' && row.category_method === 'user')).toBe(true);
  await page.getByRole('button', { name: /^Изменить категорию операции / }).first().click();
  await editor.getByRole('button', { name: 'Правило для контрагента', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Категория операции', exact: true })).toHaveCount(0);
  await choose(page, 'Категория', 'Аренда');
  await choose(page, 'Применить', 'К существующим и будущим');
  await editor.getByRole('button', { name: 'Применить правило', exact: true }).click();
  await expect(editor).toHaveCount(0);
  await page.getByRole('button', { name: 'Фильтры', exact: true }).click();
  await choose(page, 'Категория', 'Аренда');
  await page.getByRole('button', { name: 'Применить', exact: true }).click();
  await expect(page.getByRole('table').first()).toContainText('Аренда');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Выгрузить XLSX', exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/\.xlsx$/);
  await page.getByRole('link', { name: /^Открыть контрагента / }).first().click();
  await expect(page.getByRole('heading', { name: 'Оборот по месяцам', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Операции контрагента', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Сбросить фильтр контрагента', exact: true })).toBeVisible();
});

test('all four negative presets and a combined scenario compare, save, edit and delete through the API', async ({ page, request }) => {
  const w = await workspace(page, request, true);
  const due = dateAfter(today(), 3);
  await w.post('/events', { title: 'Audit future receipt', date: due, amount: 20000, direction: 'in', counterparty_name: 'Audit client', additional: true });
  await w.post('/recurring', { title: 'Audit rent', amount: 10000, direction: 'out', period: 'monthly', day_of_month: 28, category: 'rent', confirmed: true });
  await page.goto('/scenarios');
  for (const condition of ['Падение выручки', 'Внеплановый расход', 'Постоянные расходы', 'Задержка оплаты']) {
    await page.getByRole('button', { name: condition, exact: true }).click();
    if (condition === 'Задержка оплаты') await choose(page, 'Клиент с плановым поступлением', 'Audit client');
    await expect(page.getByText('Изменение минимального остатка:', { exact: false })).toBeVisible({ timeout: 60000 });
    await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  }
  await page.getByRole('button', { name: 'Свой сценарий', exact: true }).click();
  await page.getByRole('button', { name: /^\+ .*выручк/i }).click();
  await page.getByRole('button', { name: '+ Новая покупка', exact: true }).click();
  await page.getByLabel('Сумма, ₽', { exact: true }).fill('12345.67');
  await expect(page.getByText('Изменение минимального остатка:', { exact: false })).toBeVisible({ timeout: 60000 });
  await page.locator('main').getByRole('button', { name: 'Сохранить', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название сценария', { exact: true }).fill('AUDIT-COMBINED');
  // A worker update can refresh the comparison while the save dialog is open.
  // Saving must wait, rather than silently ignoring a click during that refresh.
  let blockNextPreview = true, releasePreview;
  const released = new Promise(resolve => { releasePreview = resolve; });
  await page.route(/\/scenarios\/preview(?:\?|$)/, async route => {
    if (blockNextPreview) { blockNextPreview = false; await released; }
    await route.continue();
  });
  const refreshing = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/scenarios/preview') && request.method() === 'POST');
  await w.post('/events', { title: 'Audit background refresh', date: due, amount: 123, direction: 'out', additional: true });
  await refreshing;
  await expect(dialog.getByRole('button', { name: 'Сохранить', exact: true })).toBeDisabled();
  releasePreview();
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('status').filter({ hasText: 'Сценарий сохранён' })).toBeVisible();
  let saved = (await w.get('/scenarios'))[0];
  expect(saved.steps).toHaveLength(2);
  await page.reload();
  await choose(page, 'Сохранённый сценарий', 'AUDIT-COMBINED');
  await expect(page.getByLabel('Сумма, ₽', { exact: true })).toHaveValue('12345.67');
  await page.getByRole('link', { name: 'Открыть прогноз по сценарию', exact: true }).click();
  await expect(page.getByText('Выбран сохранённый сценарий', { exact: false })).toBeVisible();
  await choose(page, 'Горизонт прогноза', '60 дней');
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  await page.goto('/scenarios');
  await choose(page, 'Сохранённый сценарий', 'AUDIT-COMBINED');
  await page.getByLabel('Сумма, ₽', { exact: true }).fill('23456.78');
  await expect(page.getByText('Изменение минимального остатка:', { exact: false })).toBeVisible({ timeout: 60000 });
  await page.locator('main').getByRole('button', { name: 'Сохранить', exact: true }).click();
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  saved = (await w.get('/scenarios'))[0];
  expect(saved.steps.find(step => step.kind === 'add_expense').amount).toBe(23456.78);
  await page.getByRole('button', { name: 'Удалить сценарий', exact: true }).click();
  await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(await w.get('/scenarios')).toHaveLength(0);
});

test('tax preview splits kopecks, calendar links to the tax source, cancellation preserves bank facts', async ({ page, request }) => {
  const w = await workspace(page, request, true);
  await page.goto('/taxes');
  // The asynchronously loaded calendar changes the form's vertical position.
  // Open the picker after those rows exist, so scrolling does not close it.
  await expect(page.getByRole('link', { name: 'Сроки ФНС', exact: true }).first()).toBeVisible();
  await choose(page, 'Вид платежа', 'НДС за квартал: три платежа');
  await page.getByLabel('Название обязательства', { exact: true }).fill('AUDIT-VAT');
  await page.getByLabel('Налоговый год', { exact: true }).fill('2026');
  await page.getByLabel('Подтверждённая сумма, ₽', { exact: true }).fill('100.01');
  await page.getByLabel('Откуда получена сумма', { exact: true }).fill('Synthetic audit liability');
  await expect(page.getByRole('combobox', { name: 'Как учесть в прогнозе', exact: true })).toContainText('Новый платёж — включить всю сумму по графику');
  await page.getByRole('checkbox', { name: /Подтверждаю сумму/ }).press('Space');
  await page.getByRole('button', { name: 'Рассчитать график платежей', exact: true }).click();
  await expect(page.getByText('Проверьте перед сохранением', { exact: true })).toBeVisible();
  expect((await w.get('/taxes?year=2026&months=12')).obligations).toHaveLength(0);
  await page.getByRole('button', { name: 'Подтвердить и добавить', exact: true }).click();
  await expect(page.getByRole('heading', { name: /AUDIT-VAT/ })).toBeVisible();
  const liability = (await w.get('/taxes?year=2026&months=12')).obligations[0];
  expect(liability.payments).toHaveLength(3);
  expect(liability.payments.reduce((sum, p) => sum + Math.round(p.amount*100), 0)).toBe(10001);
  await page.getByRole('link', { name: new RegExp(`^${liability.payments[0].date} `) }).click();
  await page.getByRole('button', { name: 'Открыть: AUDIT-VAT', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('link', { name: 'Открыть связанный раздел', exact: true })).toHaveAttribute('href', '/taxes');
  await dialog.getByRole('link', { name: 'Открыть связанный раздел', exact: true }).click();
  await page.getByRole('button', { name: 'Отменить оставшиеся платежи', exact: true }).click();
  await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('Отменено', { exact: true })).toBeVisible();
  expect((await w.get('/operations?limit=1')).total).toBe(240);
  await page.goto('/plan-fact');
  await choose(page, 'Группировка', 'По неделям');
  await choose(page, 'Показать на графике', 'Поступления');
  await page.getByRole('button', { name: 'Обновить', exact: true }).click();
  await expect(page.getByRole('img', { name: /График плана и факта/ })).toBeVisible();
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
});

test('risk action preview does not save, apply changes the real plan and recurring controls persist', async ({ page, request }) => {
  const w = await workspace(page, request, true);
  const expense = await w.post('/events', { title: 'AUDIT-GAP-EXPENSE', date: dateAfter(today(), 2), amount: 500000, direction: 'out', additional: true });
  await page.goto('/risks');
  await expect(page.getByText('AUDIT-GAP-EXPENSE', { exact: false }).first()).toBeVisible({ timeout: 60000 });
  const action = page.getByRole('article', { name: /AUDIT-GAP-EXPENSE/ });
  await action.getByRole('checkbox').press('Space');
  await page.getByRole('button', { name: 'Посмотреть эффект', exact: true }).click();
  await expect(page.getByText('Нехватка после изменений', { exact: true })).toBeVisible({ timeout: 60000 });
  expect((await w.get('/events')).find(event => event.id === expense.id).date).toBe(expense.date);
  await action.getByRole('button', { name: 'Применить к плану', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Подтвердить', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect.poll(async () => (await w.get('/events')).find(event => event.id === expense.id).date).toBe(dateAfter(expense.date, 14));
  await page.goto('/recurring');
  await page.getByRole('button', { name: 'Добавить платёж', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название', { exact: true }).fill('AUDIT-RECURRING');
  await dialog.getByLabel('Сумма, ₽', { exact: true }).fill('2345.67');
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const row = page.getByRole('row').filter({ hasText: 'AUDIT-RECURRING' });
  await row.getByRole('button', { name: 'Отключить', exact: true }).click();
  await expect(row).toContainText('Отключён');
  await row.getByRole('button', { name: 'Включить', exact: true }).click();
  await expect(row).toContainText('Подтверждён');
  await row.getByRole('button', { name: 'Изменить', exact: true }).click();
  await dialog.getByLabel('Сумма, ₽', { exact: true }).fill('3456.78');
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(row).toContainText('3 456,78');
  await row.getByRole('button', { name: 'Удалить', exact: true }).click();
  await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).click();
  await expect(row).toHaveCount(0);
});

test('stale statement risk counts from today and labels the actual explanation date', async ({ page, request }, testInfo) => {
  const w = await workspace(page, request, true, dateAfter(today(), -26));
  const firstRiskDate = dateAfter(today(), 2);
  const laterDate = dateAfter(today(), 3);
  await w.post('/events', { title: 'QA-FIRST-RISK', date: firstRiskDate, amount: 500000, direction: 'out', additional: true });
  await w.post('/events', { title: 'QA-LATER-PAYMENT', date: laterDate, amount: 200000, direction: 'out', additional: true });
  const forecast = await w.get('/forecast');
  const gap = forecast.gaps[0];
  expect(forecast.as_of).toBe(dateAfter(today(), -26));
  expect(gap.date).toBe(firstRiskDate);
  expect(gap.days_left).toBe(2);
  expect(gap.worst_date >= laterDate).toBe(true);
  await page.goto('/risks');
  await expect(page.getByText('До проблемы', { exact: true }).locator('..')).toContainText('2 дн.');
  const displayed = day => day.split('-').reverse().join('.');
  await expect(page.getByText(`Состав остатка к ${displayed(gap.explanation.date)}`, { exact: false })).toBeVisible();
  await expect(page.getByText(`Первая возможная нехватка: ${displayed(firstRiskDate)}.`, { exact: false })).toBeVisible();
  await expect(page.getByText('Платежи до даты риска.', { exact: false })).toHaveCount(0);
  await expect(page.locator('strong').filter({ hasText: /^QA-LATER-PAYMENT$/ })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('risk-dates-fixed.png'), fullPage: true });
});

test('source controls and synthetic FNS XML persist without manufacturing bank facts', async ({ page, request }) => {
  const w = await workspace(page, request, true);
  await page.goto('/sources');
  const source = page.getByRole('article').first();
  await source.getByRole('button', { name: 'Настроить', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Название', { exact: true }).fill('AUDIT-IMPORT');
  await dialog.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(source).toContainText('AUDIT-IMPORT');
  await source.getByRole('button', { name: 'Отключить', exact: true }).click();
  await expect(source).toContainText('Отключён');
  await source.getByRole('button', { name: 'Включить', exact: true }).click();
  await expect(source).toContainText('Ожидает проверки');
  await page.getByRole('button', { name: /^ФНС Документы/ }).click();
  const xml = '<EGRUL ДатаВыг="2026-10-24"><СвЮЛ ИНН="9723161623" ОГРН="1234567890127" ДатаВып="2026-10-20"><СвНаимЮЛ НаимЮЛПолн="Synthetic UI registry audit"/></СвЮЛ></EGRUL>';
  await page.getByLabel('Загрузить документ ФНС', { exact: true }).setInputFiles({ name: 'synthetic-egrul.xml', mimeType: 'application/xml', buffer: Buffer.from(xml) });
  await expect(page.getByRole('heading', { name: 'Предпросмотр реквизитов', exact: true })).toBeVisible();
  expect(await w.get('/registry')).toHaveLength(0);
  await page.getByRole('button', { name: 'Подтвердить и сохранить сведения ФНС', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Сведения ФНС сохранены' })).toBeVisible();
  expect((await w.get('/operations?limit=1')).total).toBe(240);
  expect(await w.get('/registry')).toHaveLength(1);
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.reload();
  await expect(source).toContainText('AUDIT-IMPORT');
  await source.getByText('Ещё действия', { exact: true }).click();
  await source.getByRole('button', { name: 'Удалить', exact: true }).click();
  await expect(dialog.getByRole('checkbox', { name: 'Сохранить импортированные операции', exact: true })).toBeChecked();
  await dialog.getByRole('button', { name: 'Подтвердить', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect((await w.get('/operations?limit=1')).total).toBe(240);
  await page.goto('/methodology');
  await expect(page.getByRole('heading', { name: 'Проверка контрольного датасета', exact: true })).toBeVisible();
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  await page.goto('/admin');
  await expect(page.getByRole('status').filter({ hasText: '403 · У вас нет доступа' })).toBeVisible();
});

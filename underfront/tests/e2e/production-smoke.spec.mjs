import { test, expect } from '@playwright/test';
import { randomUUID, randomBytes } from 'node:crypto';

for (const [label, url] of [['canonical', process.env.E2E_PUBLIC_URL], ['fallback', process.env.E2E_PUBLIC_FALLBACK_URL]]) {
test(`public ${label} deployment restores anonymous and authenticated sessions`, async ({ page, request }) => {
  test.skip(!url, 'Opt in to the public deployment check.');
  const failures = [];
  page.on('pageerror', error => failures.push(error.message));
  page.on('requestfailed', request => failures.push(`${request.method()} ${new URL(request.url()).pathname}: ${request.failure()?.errorText}`));
  page.on('response', response => { if (response.status() >= 400 && new URL(response.url()).pathname.startsWith('/_next/')) failures.push(`asset HTTP ${response.status()} ${new URL(response.url()).pathname}`); });
  try {
    await page.goto(url + '/overview', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(/\/login(?:\?|$)/, { timeout: 45000 });
    const landing = label === 'canonical' ? process.env.E2E_PUBLIC_CANONICAL_REDIRECT_URL || url : url;
    expect(new URL(page.url()).origin).toBe(new URL(landing).origin);
    await expect(page.getByRole('button', { name: 'Войти', exact: true })).toBeVisible();
    const email = `deploy-smoke-${randomUUID()}@example.invalid`, password = randomBytes(20).toString('hex');
    const registered = await request.post(url + '/v1/auth/register', { data: { email, password, consent_pd: true } });
    expect(registered.status()).toBe(201);
    await page.getByLabel('Электронная почта', { exact: true }).fill(email);
    await page.getByLabel('Пароль', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page).toHaveURL(/\/companies\/new$/);
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Новая компания', exact: true })).toBeVisible();
    expect(failures).toEqual([]);
  } finally {
    console.log('Public browser diagnostics:', JSON.stringify(failures));
  }
});
}

test('public deployment blocks stale spending and replaces a payment with one invoice', async ({ page, request }) => {
  const url = process.env.E2E_PUBLIC_URL;
  test.skip(!url, 'Opt in to the public deployment check.');
  const dateAt = offset => { const day = new Date(); day.setUTCDate(day.getUTCDate() + offset); return day.toISOString().slice(0, 10); };
  const email = `deploy-business-${randomUUID()}@example.invalid`, password = randomBytes(20).toString('hex');
  const registered = await request.post(url + '/v1/auth/register', { data: { email, password, consent_pd: true } });
  expect(registered.status()).toBe(201);
  const headers = { Authorization: `Bearer ${(await registered.json()).access_token}` };
  const name = 'Disposable deployment business check';
  const created = await request.post(url + '/v1/companies', { headers, data: { name, legal_form: 'ООО', industry: 'Tests' } });
  expect(created.status()).toBe(201);
  const base = `${url}/v1/companies/${(await created.json()).id}`;
  const get = async path => { const response = await request.get(base + path, { headers }); expect(response.status(), path).toBe(200); return response.json(); };
  const post = async (path, data) => { const response = await request.post(base + path, { headers, data }); expect(response.status(), path).toBe(201); return response.json(); };
  try {
    let csv = 'operation_date;amount;direction;counterparty_name;payment_purpose;balance_eod;operation_id\n';
    for (let day = 90; day >= 26; day--) {
      csv += `${dateAt(-day)};1000;in;Synthetic buyer ${day};Sales;100000;in-${day}\n${dateAt(-day)};1000;out;Synthetic supplier ${day};Materials;100000;out-${day}\n`;
    }
    const upload = await request.post(base + '/uploads', { headers, multipart: { file: { name: 'deployment-check.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) } } });
    expect(upload.status()).toBe(202);
    const job = (await upload.json()).id;
    await expect.poll(async () => (await (await request.get(`${url}/v1/jobs/${job}`, { headers })).json()).status, { timeout: 90000 }).toBe('done');
    await expect.poll(async () => (await get('/updates')).pending_jobs, { timeout: 90000 }).toBe(0);
    const forecast = await get('/forecast');
    expect(forecast.as_of).toBe(dateAt(-26));
    expect(forecast.spending_available).toBe(false);
    expect(forecast.probability_reliable).toBe(false);
    expect(forecast.safe_to_spend).toBe(0);
    const plan = await get(`/plan-fact?from=${dateAt(-27)}&to=${dateAt(-27)}`);
    expect(plan[0].plan_available).toBe(false);
    expect(plan[0].plan_in).toBeNull();
    const event = await post('/events', { date: dateAt(1), amount: 10000, direction: 'out', title: 'Deployment repair plan', additional: true });
    const invoice = await post('/invoices', { number: 'DEPLOYMENT-REPLACEMENT', direction: 'received', amount: 250000, issued_at: dateAt(0), due_at: dateAt(2), additional: true, replaces_event_id: event.id });
    const events = await get('/events');
    expect(events.find(item => item.id === event.id).status).toBe('linked');
    expect(events.filter(item => item.source === 'invoice')).toHaveLength(1);
    expect(invoice.replaces_event_id).toBe(event.id);
    expect((await request.patch(`${url}/v1/events/${event.id}`, { headers, data: { amount: 99999 } })).status()).toBe(409);
    await page.goto(url + '/login');
    await page.getByLabel('Электронная почта', { exact: true }).fill(email);
    await page.getByLabel('Пароль', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Войти', exact: true }).click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.getByRole('alert').filter({ hasText: 'Текущий остаток неизвестен' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Ключевые показатели' })).toContainText('Нет рекомендации');
    await page.goto(url + '/documents');
    await page.getByRole('row').filter({ hasText: invoice.number }).getByRole('button', { name: 'Изменить', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('combobox', { name: 'Как учесть в прогнозе', exact: true })).toContainText('Уточнение платежа из календаря');
    await expect(dialog.getByRole('combobox', { name: 'Как учесть в прогнозе', exact: true })).toBeDisabled();
    expect((await request.delete(`${url}/v1/invoices/${invoice.id}`, { headers })).status()).toBe(204);
    expect((await get('/events')).find(item => item.id === event.id).status).toBe('expected');
  } finally {
    // Remove only the synthetic company created by this check.
    expect((await request.delete(base, { headers, data: { confirm_name: name } })).status()).toBe(204);
  }
});

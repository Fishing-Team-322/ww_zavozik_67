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

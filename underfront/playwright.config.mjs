import { defineConfig, devices } from '@playwright/test';

const originIP = process.env.E2E_PUBLIC_ORIGIN_IP;
if (originIP && !/^(\d{1,3}\.){3}\d{1,3}$/.test(originIP)) throw new Error('Invalid diagnostic origin IP');

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    ...devices['Desktop Chrome'],
    channel: process.env.E2E_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined),
    launchOptions: originIP ? { args: ['--no-proxy-server', `--host-resolver-rules=MAP ${new URL(process.env.E2E_PUBLIC_URL).hostname} ${originIP}`] } : {},
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});

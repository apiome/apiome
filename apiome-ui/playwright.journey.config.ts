import { defineConfig, devices } from '@playwright/test';
import {
  BASE_URL,
  MOCK_OAUTH_PORT,
  MOCK_OAUTH_URL,
  UI_PORT,
  journeyServerEnv,
} from './e2e/journey/support/env';

/**
 * Playwright configuration for the OLO-7.4 end-to-end journey suite (#4226) — the MVP
 * acceptance gate of the OAuth Login & Onboarding roadmap.
 *
 * Runs `e2e/journey/` only, strictly serially (the journey is one continuous story whose
 * steps build on each other), against:
 *   - a dedicated Next.js dev server on :3100 wired to the mock OAuth providers,
 *   - the mock provider server on :8091 (started here),
 *   - the real REST API + Postgres, which must already be up (`docker compose up --wait`
 *     from the repo root; the global setup fails fast with instructions otherwise).
 *
 * Run with: `yarn test:e2e:journey` (see e2e/journey/README.md).
 */
export default defineConfig({
  testDir: './e2e/journey',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,

  globalSetup: './e2e/journey/support/global-setup.ts',

  reporter: [['html', { outputFolder: 'playwright-report-journey', open: 'never' }], ['list']],

  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: [
    {
      command: 'node e2e/support/mock-oauth-server.mjs',
      url: `${MOCK_OAUTH_URL}/__mock__/health`,
      env: { MOCK_OAUTH_PORT: String(MOCK_OAUTH_PORT) },
      reuseExistingServer: !process.env.CI,
      timeout: 30 * 1000,
    },
    {
      command: `yarn dev --port ${UI_PORT}`,
      url: `${BASE_URL}/login`,
      env: journeyServerEnv(),
      reuseExistingServer: false,
      timeout: 240 * 1000,
    },
  ],

  /* Journey steps traverse full OAuth round-trips plus dev-server compiles. */
  timeout: 120 * 1000,
  expect: {
    timeout: 15 * 1000,
  },
});

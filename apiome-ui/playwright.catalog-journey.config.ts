import { defineConfig, devices } from '@playwright/test';
import {
  BASE_URL,
  MOCK_OAUTH_PORT,
  MOCK_OAUTH_URL,
  UI_PORT,
  catalogJourneyServerEnv,
} from './e2e/journey/support/env';

/**
 * Playwright configuration for the Catalog → Project journey (RC6-H1, #6208).
 *
 * Runs `e2e/journey/catalog-project-journey.spec.ts` alone, serially, against:
 *   - a dedicated Next.js server on :3100 with **no preview override** — RC6's released
 *     surfaces only (`catalogJourneyServerEnv`);
 *   - the mock OAuth provider on :8091 (sign-in only);
 *   - the real REST API + Postgres, which must already be up (the global setup fails fast with
 *     instructions otherwise).
 *
 * `CATALOG_JOURNEY_USE_BUILD=1` serves the production build already made with `yarn build`
 * (CI does this: no per-route dev compiles, so the run stays well under five minutes). Build
 * with the same empty `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES`, because it is inlined at build time.
 *
 * Run with: `yarn test:e2e:catalog-journey` (see e2e/journey/README.md). CI:
 * `.github/workflows/e2e-catalog-journey.yml`.
 */
export default defineConfig({
  testDir: './e2e/journey',
  testMatch: 'catalog-project-journey.spec.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,

  globalSetup: './e2e/journey/support/global-setup.ts',

  reporter: [['html', { outputFolder: 'playwright-report-catalog-journey', open: 'never' }], ['list']],

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
      command: process.env.CATALOG_JOURNEY_USE_BUILD
        ? `npx next start -p ${UI_PORT}`
        : `yarn dev --port ${UI_PORT}`,
      url: `${BASE_URL}/login`,
      env: catalogJourneyServerEnv(),
      reuseExistingServer: false,
      timeout: 240 * 1000,
    },
  ],

  /* A step that imports or converts waits on a background job; the whole journey stays < 5 min. */
  timeout: 180 * 1000,
  expect: {
    timeout: 15 * 1000,
  },
});

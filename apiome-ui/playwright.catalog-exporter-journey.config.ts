import { defineConfig, devices } from '@playwright/test';
import {
  BASE_URL,
  MOCK_OAUTH_PORT,
  MOCK_OAUTH_URL,
  UI_PORT,
  catalogExporterJourneyServerEnv,
} from './e2e/journey/support/env';

/**
 * Playwright configuration for the Catalog Exporter journey (X2, #6223).
 *
 * Runs `e2e/journey/catalog-exporter-journey.spec.ts` alone, serially, against:
 *   - a dedicated Next.js server with the preview override set to `CATALOG_EXPORTER_PREVIEW`
 *     (`export-studio` while the studio is held back, nothing once it ships) —
 *     `catalogExporterJourneyServerEnv`;
 *   - the mock OAuth provider (sign-in only);
 *   - the real REST API + Postgres, which must already be up.
 *
 * `CATALOG_EXPORTER_JOURNEY_USE_BUILD=1` serves the production build already made with
 * `yarn build` — build it with the same `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES`, which is inlined at
 * build time.
 *
 * Run with: `yarn test:e2e:catalog-exporter-journey`. CI: the `exporter` job of
 * `.github/workflows/e2e-catalog-journey.yml`.
 */
export default defineConfig({
  testDir: './e2e/journey',
  testMatch: 'catalog-exporter-journey.spec.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,

  globalSetup: './e2e/journey/support/global-setup.ts',

  reporter: [['html', { outputFolder: 'playwright-report-catalog-exporter-journey', open: 'never' }], ['list']],

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
      command: process.env.CATALOG_EXPORTER_JOURNEY_USE_BUILD
        ? `npx next start -p ${UI_PORT}`
        : `yarn dev --port ${UI_PORT}`,
      url: `${BASE_URL}/login`,
      env: catalogExporterJourneyServerEnv(),
      reuseExistingServer: false,
      timeout: 240 * 1000,
    },
  ],

  /* Imports and export jobs run in the background; three imports share one step. */
  timeout: 300 * 1000,
  expect: {
    timeout: 15 * 1000,
  },
});

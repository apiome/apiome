import {defineConfig, devices} from '@playwright/test';

/**
 * Browser tests for the docs site's own components (DOCS-1.3, #5620).
 *
 * Runs `e2e/` against the production build served by `docusaurus serve`, so what is tested is
 * what ships. Build first (`yarn docs:build`), then `yarn workspace apiome-docs test:e2e`.
 * Set `DOCS_CHROMIUM_PATH` when Playwright's own browser is not installed.
 */
const PORT = Number(process.env.DOCS_E2E_PORT || 3210);

export default defineConfig({
  testDir: './e2e',
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PORT}/apiome/`,
    launchOptions: {executablePath: process.env.DOCS_CHROMIUM_PATH || undefined},
  },
  projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
  webServer: {
    command: `docusaurus serve --port ${PORT} --no-open`,
    url: `http://localhost:${PORT}/apiome/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60 * 1000,
  },
});

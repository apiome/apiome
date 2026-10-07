import { defineConfig, devices } from '@playwright/test';
import { dotEnvValues } from './e2e/journey/support/env';
import { A11Y_SPEC_FILES } from './e2e/a11y/routes';

/**
 * Playwright configuration for the accessibility gate — HIVE-10.2 (#5338) — and the OLO-3.5
 * login a11y + visual suite (#4203).
 *
 * HIVE-10.2 widened it from the login suite to the whole redesign: `e2e/a11y/**` (the axe gate
 * over the route ledger, the keyboard walk, the screen-reader smoke) plus every inline-markup
 * spec the ledger names (`A11Y_SPEC_FILES`). None of it needs Postgres or a session: fixture
 * pages mount into `/login`, and the galleries under `/design-system` render signed out.
 * CI runs it in `.github/workflows/apiome-ui-a11y.yml`.
 *
 * Runs `e2e/login-a11y.spec.ts` against a dedicated Next.js dev server on :3200 booted with a
 * *pinned* environment so the login "front door" renders identically everywhere:
 *   - GitHub + GitLab SSO are enabled (dummy credentials) → the SSO-first, collapsed-credentials
 *     layout (OLO-3.1) is exercised, including the "Connecting…" loading state;
 *   - the beta background is disabled so the committed visual snapshots stay deterministic.
 *
 * The suite never reaches a real provider: the loading test holds the `/api/auth/signin/*`
 * request open instead of following the redirect. Only `GET /login` is rendered, so no live
 * Postgres is required to run it.
 *
 * Run with: `yarn test:e2e:a11y` · refresh baselines with `yarn test:e2e:a11y --update-snapshots`.
 */
const UI_PORT = Number(process.env.A11Y_UI_PORT || 3200);
const BASE_URL = `http://localhost:${UI_PORT}`;

/** Env for the app under test: `.env` values, then the pins that make rendering deterministic. */
function a11yServerEnv(): Record<string, string> {
  return {
    ...dotEnvValues(),
    // Stop scripts/run.sh from re-sourcing .env over these pins.
    APIOME_LOAD_DOTENV: '0',
    BETTER_AUTH_URL: BASE_URL,
    BETTER_AUTH_SECRET:
      process.env.BETTER_AUTH_SECRET || dotEnvValues().BETTER_AUTH_SECRET || 'olo-a11y-secret',
    // Enable exactly GitHub + GitLab so the SSO-first layout renders the same in every env.
    GITHUB_ID: 'mock-github-client',
    GITHUB_SECRET: 'mock-github-secret',
    GITLAB_CLIENT_ID: 'mock-gitlab-client',
    GITLAB_CLIENT_SECRET: 'mock-gitlab-secret',
    // Beta background is decorative and animated — off, so snapshots are pixel-stable.
    NEXT_PUBLIC_BETA_MODE: '',
  };
}

export default defineConfig({
  testDir: './e2e',
  testMatch: ['login-a11y.spec.ts', 'a11y/**/*.spec.ts', ...A11Y_SPEC_FILES],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,

  reporter: [['html', { outputFolder: 'playwright-report-a11y', open: 'never' }], ['list']],

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    // CI (`A11Y_USE_BUILD=1`) serves the production build it has just made: `next dev` can serve
    // a stale CSS chunk, which makes axe pass or fail for the wrong reason (HIVE-10.2).
    command: process.env.A11Y_USE_BUILD ? `npx next start -p ${UI_PORT}` : `yarn dev --port ${UI_PORT}`,
    url: `${BASE_URL}/login`,
    env: a11yServerEnv(),
    reuseExistingServer: !process.env.CI,
    timeout: 240 * 1000,
  },

  timeout: 60 * 1000,
  expect: {
    timeout: 10 * 1000,
    // Login renders gradients + backdrop-blur; allow a small tolerance for sub-pixel AA drift.
    toHaveScreenshot: { maxDiffPixelRatio: 0.02, animations: 'disabled' },
  },
});

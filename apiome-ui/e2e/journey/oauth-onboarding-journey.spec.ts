/**
 * OLO-7.4 end-to-end journey (#4226) — the MVP acceptance gate for the OAuth Login &
 * Onboarding roadmap (#4184 / epic #4222).
 *
 * One continuous story against the real app + REST + Postgres with mocked providers:
 *
 *   1. New user signs up via mocked **GitHub** → OAuth signup wizard → first tenant
 *      provisioned with the Free plan.
 *   2. The same email arrives via mocked **GitLab** → auto-links to the existing account,
 *      never duplicates (asserted at the storage layer).
 *   3. Unverified emails from **all three** providers are rejected with the stable
 *      `unverified-email` code.
 *   4. A verified zero-tenant user arrives via mocked **Microsoft (Entra ID)** → the
 *      first-tenant onboarding wizard runs in place: slug availability, Free-license
 *      summary, provision, dashboard.
 *   5. Member invites succeed up to the Free-tier seat limit (5) and the structured
 *      `license-seats-exhausted` refusal surfaces in the members UI.
 *   6. A two-tenant user switches tenants from the header switcher, and the choice
 *      survives a reload (durable last-active tenant).
 *
 * Stack contract: REST + Postgres must already be up (`docker compose up --wait`); the
 * mock provider server and a dedicated UI dev server are started by
 * `playwright.journey.config.ts`. See `e2e/journey/README.md`.
 */
import { test, expect, type Page } from '@playwright/test';
import { setMockPersona, type MockPersona } from './support/mock-oauth';
import {
  closeDb,
  countUsersByEmail,
  listLinkedProviders,
  seedVerifiedUser,
} from './support/db';

/** Unique-per-run suffix so repeated runs never collide on emails, slugs, or ids. */
const RUN = Date.now().toString(36);
/** Base for numeric provider-side user ids, unique per run. */
const ID_BASE = Date.now() % 1_000_000_000;

/** Persona factory: one identity as asserted by one provider. */
function persona(overrides: Partial<MockPersona> & { idOffset: number }): MockPersona {
  const { idOffset, ...rest } = overrides;
  return {
    email: `journey.${RUN}@example.test`,
    name: 'Journey User',
    login: `journey-${RUN}`,
    providerUserId: String(ID_BASE + idOffset),
    verified: true,
    ...rest,
  };
}

const RILEY_EMAIL = `riley.${RUN}@example.test`;
const WREN_EMAIL = `wren.${RUN}@example.test`;
const UMA_EMAIL = `uma.${RUN}@example.test`;

const RILEY_ORG = `Riley Org ${RUN}`;
const WREN_ORG = `Wren Works ${RUN}`;

/** Button label per provider on the login page (provider registry display names). */
const PROVIDER_BUTTONS = {
  github: /continue with github/i,
  gitlab: /continue with gitlab/i,
  azure: /continue with microsoft/i,
} as const;

type ProviderId = keyof typeof PROVIDER_BUTTONS;

/**
 * Start an OAuth login from the login page: navigate there and click the provider's SSO
 * button. The mock provider redirects straight back, so callers just wait for the
 * outcome URL they expect.
 */
async function startLogin(page: Page, provider: ProviderId): Promise<void> {
  await page.goto('/login');
  await page.getByRole('button', { name: PROVIDER_BUTTONS[provider] }).click();
}

/** The header tenant-switcher trigger (shows the active tenant's name). */
function switcherButton(page: Page) {
  return page.getByRole('button', { name: 'Switch tenant' });
}

/**
 * Navigate to the dashboard shell, where the TopHeader (and its tenant switcher)
 * renders — `/ade` itself is the application launcher without the header.
 */
async function gotoDashboard(page: Page): Promise<void> {
  await page.goto('/ade/dashboard');
}

test.describe.configure({ mode: 'serial' });

test.afterAll(async () => {
  await closeDb();
});

test.describe('OLO journey — login, invariants, onboarding, license, switcher', () => {
  test('1. new GitHub user completes signup and gets a Free-plan first tenant', async ({
    page,
  }) => {
    await setMockPersona(
      persona({ idOffset: 1, email: RILEY_EMAIL, name: 'Riley Journey', login: `riley-${RUN}` })
    );

    await startLogin(page, 'github');

    // A verified email with no account routes to the OAuth signup wizard (OLO-1.3 rule c).
    await page.waitForURL(/\/signup\/oauth\?token=/);
    // The signup page shows a privacy-masked hint of the provider email (r***o@…).
    await expect(page.getByText(/r\*+y@example\.test|@example\.test/)).toBeVisible();
    // The Free plan is disclosed before the account is created.
    await expect(page.getByText('Free plan')).toBeVisible();

    await page.locator('#displayName').fill('Riley Journey');
    await page.locator('#orgName').fill(RILEY_ORG);
    // Slug auto-derives from the organization name; keep it.
    await expect(page.locator('#slug')).toHaveValue(`riley-org-${RUN}`);
    await page.getByRole('button', { name: 'Create account' }).click();

    // Signup ends in a one-time-code sign-in that lands in the app.
    await page.waitForURL(/\/ade/, { timeout: 60_000 });
    await gotoDashboard(page);
    await expect(switcherButton(page)).toContainText(RILEY_ORG);

    // The tenant switcher shows the Free license chip for the new tenant (OLO-5.x).
    await switcherButton(page).click();
    const menu = page.getByRole('menu', { name: 'Your tenants' });
    const rileyEntry = menu.getByRole('menuitem', { name: new RegExp(RILEY_ORG) });
    await expect(rileyEntry.getByTestId('tenant-license-chip')).toContainText('Free');
  });

  test('2. same email via GitLab auto-links — no duplicate account', async ({ page }) => {
    await setMockPersona(
      persona({ idOffset: 2, email: RILEY_EMAIL, name: 'Riley Journey', login: `riley-${RUN}` })
    );

    await startLogin(page, 'gitlab');

    // Straight into the app as the existing account — no signup wizard.
    await page.waitForURL(/\/ade/, { timeout: 60_000 });
    await gotoDashboard(page);
    await expect(switcherButton(page)).toContainText(RILEY_ORG);

    // Storage-layer invariants (OLO-1.3): one user row, both identities linked to it.
    expect(await countUsersByEmail(RILEY_EMAIL)).toBe(1);
    expect(await listLinkedProviders(RILEY_EMAIL)).toEqual(['github', 'gitlab']);
  });

  test('3. unverified emails are rejected by every provider with unverified-email', async ({
    page,
  }) => {
    const providers: ProviderId[] = ['github', 'gitlab', 'azure'];
    for (const [index, provider] of providers.entries()) {
      await page.context().clearCookies();
      await setMockPersona(
        persona({
          idOffset: 11 + index,
          email: UMA_EMAIL,
          name: 'Uma Unverified',
          login: `uma-${RUN}`,
          verified: false,
        })
      );

      await startLogin(page, provider);

      // Structured rejection (OLO-1.5): stable code in the URL, guidance in the banner.
      await page.waitForURL(/\/login\?.*error=unverified-email/, { timeout: 60_000 });
      await expect(page.getByTestId('login-banner')).toContainText(/verified/i);
    }

    // Rejection means rejection: no account was ever created for the address.
    expect(await countUsersByEmail(UMA_EMAIL)).toBe(0);
  });

  test('4. zero-tenant Microsoft login walks the first-tenant onboarding wizard', async ({
    page,
  }) => {
    // A verified user with zero tenant memberships (offboarded/administrative state —
    // no signup path produces it, so it is seeded directly).
    await seedVerifiedUser(WREN_EMAIL, 'Wren Journey');

    await page.context().clearCookies();
    await setMockPersona(
      persona({ idOffset: 21, email: WREN_EMAIL, name: 'Wren Journey', login: `wren-${RUN}` })
    );

    await startLogin(page, 'azure');

    // Verified email matches the seeded account → auto-link + sign-in; the onboarding
    // guard swaps the dashboard for the wizard in place (OLO-3.3 / OLO-4.1).
    await page.waitForURL(/\/ade/, { timeout: 60_000 });
    await expect(page.getByTestId('first-tenant-onboarding-wizard')).toBeVisible();

    await page.getByRole('button', { name: 'Set up your organization' }).click();
    await expect(page.getByTestId('onboarding-step-organization')).toBeVisible();
    await page.locator('input[name="organization-name"]').fill(WREN_ORG);
    // Live slug availability (OLO-4.2) confirms the auto-suggested slug.
    await expect(page.getByTestId('slug-availability')).toContainText(/available/i);
    await page.getByRole('button', { name: 'Continue' }).click();

    // The Free license is disclosed on the summary before provisioning (OLO-4.1/5.x).
    await expect(page.getByTestId('onboarding-step-summary')).toBeVisible();
    await expect(page.getByTestId('free-license-summary')).toBeVisible();
    await page.getByRole('button', { name: 'Create organization' }).click();

    await expect(page.getByTestId('onboarding-step-done')).toBeVisible();

    // "Go to your dashboard" activates the tenant via a session update; wait for that
    // POST to land before navigating, or a hard navigation would abort it mid-flight
    // (the wizard can already be unmounted by the provisioning revalidation, so its
    // disappearance is not a completion signal).
    const sessionUpdated = page.waitForResponse(
      (res) => res.url().includes('/api/auth/session') && res.request().method() === 'POST'
    );
    await page.getByRole('button', { name: 'Go to your dashboard' }).click();
    await sessionUpdated;

    // The wizard hands off to the app with the new tenant active.
    await expect(page.getByTestId('first-tenant-onboarding-wizard')).toHaveCount(0);
    await gotoDashboard(page);
    await expect(switcherButton(page)).toContainText(WREN_ORG);

    expect(await countUsersByEmail(WREN_EMAIL)).toBe(1);
    expect(await listLinkedProviders(WREN_EMAIL)).toEqual(['azure']);
  });

  test('5. member invites stop at the Free-tier seat limit with the structured refusal', async ({
    page,
  }) => {
    // Seat math (Free tier = 5): Wren (owner) + Riley + 3 seeded users fill the tenant;
    // the 6th account exists but must be refused.
    const fillers = await Promise.all(
      [1, 2, 3, 4].map((n) => {
        const email = `filler${n}.${RUN}@example.test`;
        return seedVerifiedUser(email, `Filler ${n}`).then(() => email);
      })
    );

    await page.context().clearCookies();
    await setMockPersona(
      persona({ idOffset: 21, email: WREN_EMAIL, name: 'Wren Journey', login: `wren-${RUN}` })
    );
    await startLogin(page, 'azure');
    await page.waitForURL(/\/ade/, { timeout: 60_000 });

    await page.goto('/ade/dashboard/members');
    await expect(switcherButton(page)).toContainText(WREN_ORG);
    await expect(page.getByTestId('members-invite-form')).toBeVisible();
    await expect(page.getByTestId('member-row')).toHaveCount(1);

    const invite = async (email: string) => {
      await page.locator('#inviteEmail').fill(email);
      await page.getByRole('button', { name: 'Invite member' }).click();
    };

    for (const [index, email] of [RILEY_EMAIL, ...fillers.slice(0, 3)].entries()) {
      await invite(email);
      await expect(page.getByTestId('member-row')).toHaveCount(index + 2);
      await expect(page.getByTestId('members-error')).toHaveCount(0);
    }

    // Seat 6: refused with the license-seats-exhausted guidance; no member appears.
    await invite(fillers[3]);
    await expect(page.getByTestId('members-error')).toContainText(/seat/i);
    await expect(page.getByTestId('member-row')).toHaveCount(5);
  });

  test('6. a two-tenant user switches tenants from the header, durably', async ({ page }) => {
    // Riley now belongs to two tenants: their own (test 1) and Wren's (invited, test 5).
    await page.context().clearCookies();
    await setMockPersona(
      persona({ idOffset: 1, email: RILEY_EMAIL, name: 'Riley Journey', login: `riley-${RUN}` })
    );
    await startLogin(page, 'github');
    await page.waitForURL(/\/ade/, { timeout: 60_000 });
    await gotoDashboard(page);
    await expect(switcherButton(page)).toContainText(RILEY_ORG);

    const selectTenant = async (name: string) => {
      await switcherButton(page).click();
      await page
        .getByRole('menu', { name: 'Your tenants' })
        .getByRole('menuitem', { name: new RegExp(name) })
        .click();
      await expect(switcherButton(page)).toContainText(name);
    };

    await selectTenant(WREN_ORG);
    await selectTenant(RILEY_ORG);
    await selectTenant(WREN_ORG);

    // The durable last-active cookie (OLO-6.1) is written fire-and-forget after the
    // switch; wait for it before reloading so the reload cannot abort the write.
    await expect
      .poll(async () => {
        const cookies = await page.context().cookies();
        return cookies.find((c) => c.name === 'apiome.last-active-tenant')?.value ?? '';
      })
      .not.toBe('');

    // The choice is durable: a reload keeps the tenant.
    await page.reload();
    await expect(switcherButton(page)).toContainText(WREN_ORG);
  });
});

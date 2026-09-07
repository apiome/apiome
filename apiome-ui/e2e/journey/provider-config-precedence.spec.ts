/**
 * OLO-8.9 (#4975) — database-driven provider configuration, end to end.
 *
 * OLO-EPIC-8 (#4966) made sign-in provider credentials editable in the `/admin` portal, stored
 * encrypted in `apiome.auth_provider_config`, and resolved **DB-over-`.env` per request**. Every
 * piece of that has unit coverage — the envelope crypto (`test_auth_provider_secret_crypto.py`),
 * the merge matrix (`provider-config-resolver.test.ts`), the per-request rebuild
 * (`better-auth-per-request-providers.test.ts`), the signed admin session (both sides). All of them
 * stub the layer beneath.
 *
 * This spec is the one that does not. It drives the whole chain against the live stack:
 *
 *   admin UI → REST CRUD → envelope-encrypted row → resolved endpoint → merge resolver →
 *   per-request Better Auth instance → a real OAuth handshake → clear the row → fallback to `.env`
 *
 * **How precedence is proved.** The credentials a sign-in uses are chosen server-side, so the only
 * place they become observable is the authorization request the app sends to the provider. The mock
 * provider ignores `client_id` entirely, so the handshake completes whichever value goes out — which
 * is exactly what lets this spec assert *which* one it was without breaking the flow.
 *
 * **Stack contract.** Beyond the usual journey requirements, REST must hold `INTERNAL_SERVICE_TOKEN`
 * (matching this suite's), `ADMIN_SESSION_SECRET` (matching the UI's), and `AUTH_CONFIG_ENC_KEY`.
 * All three default to empty in `docker-compose.yml`, so the spec probes first and skips with the
 * variable to set — see `e2e/journey/README.md`.
 */
import { test, expect, type Page } from '@playwright/test';
import { setMockPersona } from './support/mock-oauth';
import { closeDb, deleteProviderConfigRow, readProviderConfigRow } from './support/db';
import {
  captureAuthorizeClientId,
  providerConfigSourceReady,
  waitForResolvedConfig,
  waitOutProviderConfigCache,
} from './support/provider-config';

/** Unique-per-run suffix so repeated runs never collide on credentials or persona emails. */
const RUN = Date.now().toString(36);

/** The provider this story configures. GitHub is the journey's primary mocked provider. */
const PROVIDER_ID = 'github';
/** Its card/label text in the admin screen and its login button. */
const PROVIDER_LABEL = 'GitHub';

/** Path fragment of the mocked GitHub authorize endpoint, where the client id becomes visible. */
const AUTHORIZE_PATH = '/github/login/oauth/authorize';

/**
 * The `.env` credentials the suite boots with (`journeyServerEnv()`). The fallback leg asserts the
 * app returns to exactly this client id once the database row is gone.
 */
const ENV_CLIENT_ID = 'mock-github-client';

/** The credentials an admin types into the portal — deliberately distinct from the `.env` pair. */
const DB_CLIENT_ID = `db-github-client-${RUN}`;
const DB_CLIENT_SECRET = `db-github-secret-${RUN}`;

/** A verified identity with no account: every sign-in leg lands on the OAuth signup wizard. */
const PERSONA_EMAIL = `provider-config.${RUN}@example.test`;

/** Populated by the readiness probe; every test skips with this reason when the source is off. */
let skipReason = '';

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const readiness = await providerConfigSourceReady();
  skipReason = readiness.ready ? '' : readiness.reason;
  // `auth_provider_config` is a *global* table — a row left by an interrupted run would change
  // which credentials every other journey spec signs in with. Clear before as well as after.
  if (readiness.ready) {
    await deleteProviderConfigRow(PROVIDER_ID);
  }
});

test.afterAll(async () => {
  if (!skipReason) {
    await deleteProviderConfigRow(PROVIDER_ID);
  }
  await closeDb();
});

test.beforeEach(() => {
  test.skip(skipReason !== '', skipReason);
});

/** Sign in to the `/admin` portal and land on the provider-configuration screen. */
async function openAdminProviderSettings(page: Page): Promise<void> {
  await page.goto('/admin');
  await page.locator('#password').fill(process.env.ADMIN_PASSWORD ?? '');
  await page.getByRole('button', { name: 'Access Admin Portal' }).click();
  await page.waitForURL(/\/admin\/dashboard/, { timeout: 30_000 });

  await page.goto('/admin/dashboard/settings');
  await expect(page.getByRole('heading', { name: 'System Configuration' })).toBeVisible();
}

/** The provider's configuration card. Only rendered once the provider has something stored. */
function providerCard(page: Page) {
  return page.getByRole('region', { name: `${PROVIDER_LABEL} provider configuration` });
}

/**
 * Start a GitHub sign-in from the login page and report the client id that went to the provider.
 *
 * @param page Page to run the sign-in in.
 * @returns The `client_id` on the outgoing authorization request.
 */
async function signInAndCaptureClientId(page: Page): Promise<string> {
  await page.goto('/login');
  return captureAuthorizeClientId(page, AUTHORIZE_PATH, async () => {
    await page.getByRole('button', { name: /continue with github/i }).click();
  });
}

test.describe('OLO-8.9 — DB-configured provider credentials override .env, and clearing them falls back', () => {
  test('1. an admin configures GitHub credentials in the portal, and they are stored encrypted', async ({
    page,
  }) => {
    await openAdminProviderSettings(page);

    // On a clean database nothing is stored, so no cards render — the provider is added through the
    // picker. The trigger stays disabled until the list GET resolves.
    const addProvider = page.getByRole('button', { name: 'Add Provider' });
    await expect(addProvider).toBeEnabled({ timeout: 30_000 });
    await addProvider.click();

    const dialog = page.getByRole('dialog', { name: 'Add a sign-in provider' });
    await dialog.getByLabel('Search providers').fill(PROVIDER_LABEL);
    await dialog.getByRole('option', { name: new RegExp(PROVIDER_LABEL, 'i') }).first().click();

    await dialog.locator('#add-provider-client-id').fill(DB_CLIENT_ID);
    await dialog.locator('#add-provider-client-secret').fill(DB_CLIENT_SECRET);
    await dialog.getByRole('button', { name: 'Save' }).click();

    // A save that reaches REST without a KEK fails with `encryption_not_configured`; surfacing the
    // screen's own error text here names the missing variable instead of timing out anonymously.
    const card = providerCard(page);
    await expect(card, 'the provider card should appear after a successful save').toBeVisible({
      timeout: 30_000,
    });
    await expect(card).toContainText('Secret: set');
    await expect(card.locator(`#${PROVIDER_ID}-client-id`)).toHaveValue(DB_CLIENT_ID);

    // The storage-layer assertion no mocked test can make: the row exists, the secret is sealed
    // under a KEK generation, and the ciphertext does not contain what the admin typed.
    const row = await readProviderConfigRow(PROVIDER_ID);
    expect(row, 'the admin save should have written a row').not.toBeNull();
    expect(row?.clientId).toBe(DB_CLIENT_ID);
    expect(row?.encKeyId, 'the secret should be sealed under a KEK generation').toBeTruthy();
    // `toBeInstanceOf` rather than `not.toBeNull`: optional chaining yields `undefined` when the row
    // is missing, and `undefined` would slip past a null check, making the `includes` below vacuous.
    expect(row?.clientSecretEncrypted).toBeInstanceOf(Buffer);
    expect(
      row?.clientSecretEncrypted?.includes(Buffer.from(DB_CLIENT_SECRET, 'utf8')),
      'the stored blob must be ciphertext, never the plaintext secret'
    ).toBe(false);
  });

  test('2. the next sign-in uses the database credentials, not the ones in .env', async ({
    page,
  }) => {
    await page.context().clearCookies();

    // Prove the write is visible to REST before waiting on the app's in-process cache, so a failure
    // says which half is at fault. REST returns the secret decrypted — the round trip through
    // envelope encryption, end to end.
    await waitForResolvedConfig(
      PROVIDER_ID,
      (config) => config?.client_id === DB_CLIENT_ID && config?.client_secret === DB_CLIENT_SECRET
    );
    await waitOutProviderConfigCache(page);

    await setMockPersona({
      email: PERSONA_EMAIL,
      name: 'Provider Config',
      login: `provider-config-${RUN}`,
      providerUserId: String(Date.now() % 1_000_000_000),
      verified: true,
    });

    const clientId = await signInAndCaptureClientId(page);
    expect(clientId, 'the database client id should override the one in .env').toBe(DB_CLIENT_ID);

    // And the handshake completes on those credentials: a verified email with no account routes to
    // the OAuth signup wizard (OLO-1.3 rule c). DB config is a working login, not just a stored row.
    await page.waitForURL(/\/signup\/oauth\?token=/, { timeout: 60_000 });
  });

  test('3. an admin removes the stored configuration', async ({ page }) => {
    await page.context().clearCookies();
    await openAdminProviderSettings(page);

    const card = providerCard(page);
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.getByRole('button', { name: 'Remove' }).click();
    await page.getByRole('button', { name: 'Remove provider' }).click();

    // The card is only rendered for providers with something stored, so its disappearance is the
    // screen's own statement that the provider is back to .env.
    await expect(card).toBeHidden({ timeout: 30_000 });
    expect(await readProviderConfigRow(PROVIDER_ID)).toBeNull();
  });

  test('4. sign-in falls back to the .env credentials, and still works', async ({ page }) => {
    await page.context().clearCookies();

    await waitForResolvedConfig(PROVIDER_ID, (config) => config === null);
    await waitOutProviderConfigCache(page);

    await setMockPersona({
      email: PERSONA_EMAIL,
      name: 'Provider Config',
      login: `provider-config-${RUN}`,
      providerUserId: String(Date.now() % 1_000_000_000),
      verified: true,
    });

    const clientId = await signInAndCaptureClientId(page);
    expect(clientId, 'removing the row should return the app to the .env client id').toBe(
      ENV_CLIENT_ID
    );

    // The fallback is a working login, not a login outage — the whole point of degrading to env.
    await page.waitForURL(/\/signup\/oauth\?token=/, { timeout: 60_000 });
  });
});

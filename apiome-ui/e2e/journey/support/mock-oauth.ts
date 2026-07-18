/**
 * Client for the mock OAuth server's control API (OLO-7.4, #4226).
 *
 * The mock (`e2e/support/mock-oauth-server.mjs`) impersonates GitHub, GitLab, and
 * Microsoft Entra ID; the journey switches "who logs in next" by posting a persona here
 * before clicking a login button. See the server's module doc for endpoint details.
 */
import { MOCK_OAUTH_URL } from './env';

/** The identity the mock provider asserts on its next login round-trip. */
export interface MockPersona {
  /** Email address the provider reports for the user. */
  email: string;
  /** Display name on the provider profile. */
  name: string;
  /** Provider-side username/login handle. */
  login: string;
  /**
   * Stable provider-side user id (numeric string; becomes github/gitlab `id` and the
   * azure `oid` suffix). Distinct values per (persona, provider) pair keep identities
   * from colliding across providers.
   */
  providerUserId: string;
  /**
   * Whether the provider proves the email verified (GitHub emails-API `verified`,
   * GitLab `confirmed_at`, azure `email_verified` claim). False personas must be
   * rejected by the resolution engine with `unverified-email`.
   */
  verified: boolean;
}

/**
 * Set the persona the mock provider serves on its next authorization round-trip.
 *
 * @param persona The identity every provider (github/gitlab/azure) will assert.
 * @throws Error when the control API is unreachable or refuses the update.
 */
export async function setMockPersona(persona: MockPersona): Promise<void> {
  const response = await fetch(`${MOCK_OAUTH_URL}/__mock__/persona`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(persona),
  });
  if (!response.ok) {
    throw new Error(`mock OAuth persona update failed: HTTP ${response.status}`);
  }
}

/**
 * VK provider trust-gate smoke tests (OLO-9.42, #5055).
 *
 * Pins the slug on the linkable set and off the auto-link trust set: VK returns an email with no
 * verified claim, so it is `link-first` under the OLO-9.16 trust-gate rule (#5029) and its email
 * must never auto-link. Endpoint + fail-closed email behaviour live in
 * `better-auth-oauth-providers.test.ts`.
 */

import { AUTO_LINK_TRUSTED_PROVIDERS, LINKABLE_PROVIDERS } from '../lib/auth/account-resolution';

describe('VK provider trust gates (OLO-9.42)', () => {
  test('vk is linkable but not auto-link trusted (link-first)', () => {
    expect(AUTO_LINK_TRUSTED_PROVIDERS.has('vk')).toBe(false);
    expect(LINKABLE_PROVIDERS.has('vk')).toBe(true);
  });
});

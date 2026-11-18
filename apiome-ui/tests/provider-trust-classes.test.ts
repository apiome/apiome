/**
 * @jest-environment node
 *
 * Provider trust classes & the trust-gate rule (OLO-9.16, #5029).
 *
 * `provider-trust-classes.ts` is the one table that records whether a provider's email may auto-link
 * an account. These tests hold the three things that must agree with it:
 *
 *   1. the DB vocabulary (V395) — every catalog slug is admitted by both provider CHECKs, and the
 *      CHECKs admit nothing else that could sign in;
 *   2. the engine's gates — `AUTO_LINK_TRUSTED_PROVIDERS` is exactly the shipped `trusted` providers,
 *      and every `LINKABLE_PROVIDERS` slug has a recorded class;
 *   3. the engine's behaviour — a verified email from a `link-first` or `link-only` provider never
 *      auto-links and never creates an account.
 */

import * as fs from 'fs';
import * as path from 'path';

// `better-auth/api` is ESM-only; stub createAuthMiddleware (the adapter imports it at module load).
jest.mock('better-auth/api', () => ({
  createAuthMiddleware: (handler: unknown) => handler,
}));
// The default production store imports the db layer; every test injects its own store.
jest.mock('../lib/auth/resolution-store', () => ({ resolutionStore: {} }));

import { describe, test, expect } from '@jest/globals';

import {
  AUTO_LINK_TRUSTED_PROVIDERS,
  LINKABLE_PROVIDERS,
  isAutoLinkTrustedProvider,
  type ResolutionStore,
  type ResolutionUser,
} from '../lib/auth/account-resolution';
import {
  resolveBetterAuthOAuthSignIn,
  type BetterAuthOAuthContext,
} from '../lib/auth/better-auth-account-resolution';
import { PROVIDER_REGISTRY } from '../lib/auth/provider-registry';
import {
  CATALOG_PROVIDER_SLUGS,
  PROVIDER_TRUST_CLASSES,
  providerTrustClass,
} from '../lib/auth/provider-trust-classes';

const MIGRATION = path.join(
  __dirname,
  '..',
  '..',
  'apiome-db',
  'scripts',
  'V395__auth_provider_vocabulary_full_catalog_5029.sql'
);
const MIGRATION_SQL = fs.readFileSync(MIGRATION, 'utf8');

/**
 * Read the slug list of a named `ADD CONSTRAINT … CHECK (… IN ( … ))` block.
 *
 * @param constraint The constraint whose vocabulary to read.
 * @returns The slugs the constraint admits.
 */
function checkVocabulary(constraint: string): Set<string> {
  const start = MIGRATION_SQL.indexOf(`ADD CONSTRAINT ${constraint}`);
  if (start === -1) throw new Error(`constraint '${constraint}' not found in V395`);
  const block = MIGRATION_SQL.slice(start, MIGRATION_SQL.indexOf(';', start));
  return new Set([...block.matchAll(/'([a-z0-9_]+)'/g)].map((match) => match[1]));
}

/** An existing, enabled, verified account holding the address the callback claims. */
const EXISTING_USER: ResolutionUser = {
  id: 'user-ok',
  enabled: true,
  verified: true,
  email: 'ada@example.com',
  name: 'Ada',
};

/** Slugs the CHECK admits that are not sign-in providers (`gcp` is a repository-connector kind). */
const NON_SIGN_IN_SLUGS = ['gcp'];

/** The 30 slugs OLO-9.16 pre-admits for the OLO-9.17–9.49 provider tickets. */
const UPCOMING_SLUGS = [
  'slack',
  'linkedin',
  'discord',
  'salesforce',
  'notion',
  'figma',
  'linear',
  'dropbox',
  'zoom',
  'huggingface',
  'vercel',
  'railway',
  'hubspot',
  'apple',
  'facebook',
  'twitter',
  'reddit',
  'spotify',
  'twitch',
  'tiktok',
  'roblox',
  'kick',
  'kakao',
  'naver',
  'yandex',
  'paypal',
  'polar',
  'patreon',
  'gumroad',
  'paybin',
];

describe('the trust-class table covers the whole catalog', () => {
  test('every upcoming provider and every shipped provider has a class', () => {
    for (const slug of UPCOMING_SLUGS) {
      expect(CATALOG_PROVIDER_SLUGS.has(slug)).toBe(true);
    }
    for (const provider of PROVIDER_REGISTRY) {
      expect(CATALOG_PROVIDER_SLUGS.has(provider.id)).toBe(true);
    }
    // The 14 providers shipped before OLO-9.16 plus the 30 it pre-admits.
    expect(CATALOG_PROVIDER_SLUGS.size).toBe(44);
  });

  test('every entry names its ticket and its evidence', () => {
    for (const [slug, entry] of Object.entries(PROVIDER_TRUST_CLASSES)) {
      expect(['trusted', 'link-first', 'link-only']).toContain(entry.trustClass);
      expect(entry.ticket).toMatch(/^OLO-\d+\.\d+$/);
      expect(entry.evidence.length).toBeGreaterThan(0);
      expect(slug).toMatch(/^[a-z0-9]+$/);
    }
  });

  test('a provisional class is always the fail-closed link-first default', () => {
    const provisional = Object.entries(PROVIDER_TRUST_CLASSES).filter(
      ([, entry]) => entry.provisional
    );
    expect(provisional.map(([slug]) => slug).sort()).toEqual([
      'naver',
      'paybin',
      'yandex',
    ]);
    for (const [, entry] of provisional) {
      expect(entry.trustClass).toBe('link-first');
    }
  });

  test('providerTrustClass reads the table and is null outside the catalog', () => {
    expect(providerTrustClass('github')).toBe('trusted');
    expect(providerTrustClass('vk')).toBe('link-first');
    expect(providerTrustClass('wechat')).toBe('link-only');
    expect(providerTrustClass('reddit')).toBe('link-only');
    expect(providerTrustClass('not-a-provider')).toBeNull();
    // Inherited object keys are not providers.
    expect(providerTrustClass('constructor')).toBeNull();
    expect(providerTrustClass('toString')).toBeNull();
  });
});

describe('the setup guide repeats the table faithfully', () => {
  const GUIDE = fs.readFileSync(
    path.join(__dirname, '..', 'docs', 'AUTH_PROVIDER_SETUP.md'),
    'utf8'
  );

  /** The guide's rows as `slug → [class cell, ticket, evidence]`. */
  const guideRows = new Map(
    [
      ...GUIDE.matchAll(/^\| `([a-z0-9]+)` \| (.+?) \| (OLO-[\d.]+) \| (?:yes|no) \| (.+) \|$/gm),
    ].map((match) => [match[1], [match[2], match[3], match[4]]] as const)
  );

  test('the guide lists every provider with the class, ticket and evidence of record', () => {
    expect([...guideRows.keys()].sort()).toEqual([...CATALOG_PROVIDER_SLUGS].sort());
    for (const [slug, entry] of Object.entries(PROVIDER_TRUST_CLASSES)) {
      const classCell = `**${entry.trustClass}**${entry.provisional ? ' (provisional)' : ''}`;
      expect(guideRows.get(slug)).toEqual([classCell, entry.ticket, entry.evidence]);
    }
  });
});

describe('the V395 vocabulary admits exactly the catalog', () => {
  const identityVocabulary = checkVocabulary('external_auth_providers_provider_supported_ck');
  const configVocabulary = checkVocabulary('auth_provider_config_provider_id_check');

  test('both CHECKs admit every catalog slug', () => {
    for (const slug of CATALOG_PROVIDER_SLUGS) {
      expect(identityVocabulary.has(slug)).toBe(true);
      expect(configVocabulary.has(slug)).toBe(true);
    }
  });

  test('the CHECKs admit nothing beyond the catalog and the non-sign-in slugs', () => {
    const expected = [...CATALOG_PROVIDER_SLUGS, ...NON_SIGN_IN_SLUGS].sort();
    expect([...identityVocabulary].sort()).toEqual(expected);
    expect([...configVocabulary].sort()).toEqual(expected);
  });

  test('the identity CHECK keeps the enterprise SSO identity kind (V312)', () => {
    const start = MIGRATION_SQL.indexOf(
      'ADD CONSTRAINT external_auth_providers_provider_supported_ck'
    );
    const block = MIGRATION_SQL.slice(start, MIGRATION_SQL.indexOf(';', start));
    expect(block).toContain("OR provider ~ '^sso:[a-z0-9][a-z0-9-]{1,27}$'");
  });
});

describe('the engine gates follow the table (trust-gate rule)', () => {
  test('AUTO_LINK_TRUSTED_PROVIDERS is exactly the shipped trusted providers', () => {
    const shippedTrusted = [...LINKABLE_PROVIDERS].filter(
      (slug) => providerTrustClass(slug) === 'trusted'
    );
    expect([...AUTO_LINK_TRUSTED_PROVIDERS].sort()).toEqual(shippedTrusted.sort());
  });

  test('every linkable provider has a recorded class', () => {
    for (const slug of LINKABLE_PROVIDERS) {
      expect(providerTrustClass(slug)).not.toBeNull();
    }
  });

  test('no link-first or link-only provider is auto-link trusted', () => {
    for (const [slug, entry] of Object.entries(PROVIDER_TRUST_CLASSES)) {
      if (entry.trustClass === 'trusted') continue;
      expect(isAutoLinkTrustedProvider(slug)).toBe(false);
    }
  });

  test('a slug without a registry entry is inert: neither linkable nor trusted', () => {
    const registryIds = new Set(PROVIDER_REGISTRY.map((provider) => provider.id));
    const unshipped = [...CATALOG_PROVIDER_SLUGS].filter((slug) => !registryIds.has(slug));
    expect(unshipped.length).toBeGreaterThan(0);
    for (const slug of unshipped) {
      expect(LINKABLE_PROVIDERS.has(slug)).toBe(false);
      expect(AUTO_LINK_TRUSTED_PROVIDERS.has(slug)).toBe(false);
    }
  });
});

describe('the engine never trusts an email outside the trusted class', () => {
  /** A callback whose profile claims a verified email — the claim a link-first provider cannot prove. */
  const ctx: BetterAuthOAuthContext = {
    accountId: 'prov-123',
    profile: {
      email: 'ada@example.com',
      email_verified: true,
      login: 'ada',
      name: 'Ada',
    },
    tokens: {
      accessToken: 'tok',
      refreshToken: null,
      accessTokenExpiresAt: null,
    },
  };

  /**
   * A store holding one existing account for the callback's email and no bound identity.
   *
   * @returns The store and the writes it received.
   */
  function makeStore() {
    const writes = { linkIdentity: 0, createPendingSignup: 0 };
    const store: ResolutionStore = {
      async getIdentity() {
        return { found: false, userId: null };
      },
      async getUserById() {
        return EXISTING_USER;
      },
      async getUserByEmail() {
        return EXISTING_USER;
      },
      async linkIdentity() {
        writes.linkIdentity += 1;
        return { success: true };
      },
      async recordIdentityLogin() {},
      async recordUserLogin() {},
      async createPendingSignup() {
        writes.createPendingSignup += 1;
        return { id: 'pending-1' };
      },
    };
    return { store, writes };
  }

  test.each(['vk', 'wechat'])(
    'a verified-looking email from %s neither links the matching account nor signs in',
    async (provider) => {
      const { store, writes } = makeStore();

      const result = await resolveBetterAuthOAuthSignIn(provider, ctx, null, store);

      expect(result).not.toBe(true);
      expect(writes.linkIdentity).toBe(0);
    }
  );

  test('the same callback from a trusted provider does link (the control)', async () => {
    const { store, writes } = makeStore();

    const result = await resolveBetterAuthOAuthSignIn('github', ctx, null, store);

    expect(result).toBe(true);
    expect(writes.linkIdentity).toBe(1);
  });
});

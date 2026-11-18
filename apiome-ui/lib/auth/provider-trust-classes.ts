/**
 * Provider trust classes — the one documented framework for the auto-link trust decision
 * (OLO-9.16, #5029).
 *
 * Whether a provider's email may join an existing account, or create one, is a **security
 * decision**: a provider that lets a person claim an address they do not own, trusted here, is an
 * account takeover. Every provider therefore gets exactly one class, decided against one rule, and
 * recorded in {@link PROVIDER_TRUST_CLASSES} — the table the OLO-9.17–9.49 provider tickets cite.
 *
 * **The trust-gate rule.** A provider joins `AUTO_LINK_TRUSTED_PROVIDERS` (`account-resolution.ts`)
 * only when it *proves* the email is verified: a signed `email_verified` claim, or an explicit
 * verified flag from its own API that the provider's `getUserInfo` normalizes onto
 * `email_verified`. The normalization is fail-closed — a missing, malformed or false signal is
 * unverified. Everything else stays out of the set:
 *
 *  - `trusted` — the provider proves verification. A verified email auto-links the matching account
 *    or creates one; an unverified email from the same provider is refused (`unverified-email`).
 *  - `link-first` — the provider returns an email but no proof it is verified (or the proof is not
 *    established yet). The email is never trusted: sign-in resolves only through an identity that is
 *    already bound, and a person binds one from **Linked accounts** while signed in.
 *  - `link-only` — the provider exposes no email at all. Same as `link-first`, with nothing to match.
 *
 * **How the sets grow.** A provider ticket adds its slug to `LINKABLE_PROVIDERS` (always) and to
 * `AUTO_LINK_TRUSTED_PROVIDERS` (only when its class here is `trusted`), in the same change that
 * ships its registry entry. The DB vocabulary already admits every slug below (V395), so no
 * migration is needed. A `provisional` class is the fail-closed default for a provider whose email
 * semantics are confirmed at implementation: its ticket either keeps `link-first` or promotes it to
 * `trusted` by editing this table, with the proof named in `evidence`. Never promote without one.
 *
 * `provider-trust-classes.test.ts` holds the sets to this table.
 */

/** What a provider's email is worth to the account-resolution engine. */
export type ProviderTrustClass = 'trusted' | 'link-first' | 'link-only';

/** One provider's recorded trust decision. */
export interface ProviderTrustEntry {
  /** The provider's trust class. */
  trustClass: ProviderTrustClass;
  /** The roadmap ticket that ships (or shipped) the provider, e.g. `OLO-9.17`. */
  ticket: string;
  /** Why the class holds: the claim or API field that proves verification, or its absence. */
  evidence: string;
  /**
   * True when the class is the fail-closed default pending confirmation in the provider's own
   * ticket. A provisional class is always `link-first`.
   */
  provisional?: boolean;
}

/**
 * The trust class of every sign-in provider in the Better Auth catalog, keyed by provider slug
 * (Better Auth's own provider id — the value stored in `external_auth_providers.provider`).
 */
export const PROVIDER_TRUST_CLASSES: Readonly<Record<string, ProviderTrustEntry>> = {
  // ── Shipped before the catalog expansion ──────────────────────────────────────────────────────
  github: {
    trustClass: 'trusted',
    ticket: 'OLO-2.5',
    evidence: 'Primary address with `verified: true` from `/user/emails`',
  },
  gitlab: {
    trustClass: 'trusted',
    ticket: 'OLO-2.5',
    evidence: '`email_verified` claim, or `confirmed_at` on the user',
  },
  azure: {
    trustClass: 'trusted',
    ticket: 'OLO-1.4',
    evidence:
      '`xms_edov` domain-owner-verified claim (nOAuth hardening); never the bare email claim',
  },
  google: {
    trustClass: 'trusted',
    ticket: 'OLO-9.2',
    evidence: '`email_verified` id-token claim',
  },
  okta: {
    trustClass: 'trusted',
    ticket: 'OLO-9.3',
    evidence: '`email_verified` id-token claim',
  },
  aws: {
    trustClass: 'trusted',
    ticket: 'OLO-9.4',
    evidence: 'Cognito `email_verified` claim',
  },
  keycloak: {
    trustClass: 'trusted',
    ticket: 'OLO-9.5',
    evidence: '`email_verified` claim',
  },
  oidc: {
    trustClass: 'trusted',
    ticket: 'OLO-9.6',
    evidence: '`email_verified` claim from the configured issuer',
  },
  auth0: {
    trustClass: 'trusted',
    ticket: 'OLO-9.7',
    evidence: '`email_verified` claim',
  },
  atlassian: {
    trustClass: 'trusted',
    ticket: 'OLO-9.8',
    evidence: '`email_verified` from the User Identity API; absent means unverified',
  },
  bitbucket: {
    trustClass: 'trusted',
    ticket: 'OLO-9.9',
    evidence: 'Primary address with `is_confirmed` from `/2.0/user/emails`',
  },
  line: {
    trustClass: 'trusted',
    ticket: 'OLO-9.41',
    evidence:
      '`email_verified` claim, sent only with the approved email permission; absent means unverified',
  },
  vk: {
    trustClass: 'link-first',
    ticket: 'OLO-9.42',
    evidence: 'Email returned with the grant, no verified claim',
  },
  wechat: {
    trustClass: 'link-only',
    ticket: 'OLO-9.43',
    evidence: 'No email; identity is keyed on `openid` / `unionid`',
  },

  // ── Wave 1 — developer and work tools (OLO-9.17–9.29) ─────────────────────────────────────────
  slack: {
    trustClass: 'trusted',
    ticket: 'OLO-9.17',
    evidence: '`email_verified` claim (Sign in with Slack, OIDC)',
  },
  linkedin: {
    trustClass: 'trusted',
    ticket: 'OLO-9.18',
    evidence: '`email_verified` claim (Sign In with LinkedIn, OIDC)',
  },
  discord: {
    trustClass: 'trusted',
    ticket: 'OLO-9.19',
    evidence: '`verified` on `/users/@me`',
  },
  salesforce: {
    trustClass: 'trusted',
    ticket: 'OLO-9.20',
    evidence: '`email_verified` claim',
  },
  notion: {
    trustClass: 'link-first',
    ticket: 'OLO-9.21',
    evidence: 'Owner-user email from the token exchange, no verified claim',
  },
  figma: {
    trustClass: 'link-first',
    ticket: 'OLO-9.22',
    evidence: '`/v1/me` email, no verified claim',
  },
  linear: {
    trustClass: 'link-first',
    ticket: 'OLO-9.23',
    evidence: 'Viewer email, no verified claim',
  },
  dropbox: {
    trustClass: 'trusted',
    ticket: 'OLO-9.24',
    evidence: '`email_verified` on `get_current_account`',
  },
  zoom: {
    trustClass: 'trusted',
    ticket: 'OLO-9.25',
    evidence: '`verified` on `/v2/users/me`',
  },
  huggingface: {
    trustClass: 'trusted',
    ticket: 'OLO-9.26',
    evidence: '`email_verified` claim',
  },
  vercel: {
    trustClass: 'trusted',
    ticket: 'OLO-9.27',
    evidence: '`email_verified` on `/login/oauth/userinfo`',
  },
  railway: {
    trustClass: 'link-first',
    ticket: 'OLO-9.28',
    evidence: '`/oauth/me` email, no documented verified claim',
  },
  hubspot: {
    trustClass: 'link-first',
    ticket: 'OLO-9.29',
    evidence: 'Token-info email, no verified claim',
  },

  // ── Wave 2 — consumer social (OLO-9.30–9.38) ──────────────────────────────────────────────────
  apple: {
    trustClass: 'trusted',
    ticket: 'OLO-9.30',
    evidence:
      '`email_verified` id-token claim; Hide My Email relay addresses (`is_private_email`) are verified too',
  },
  facebook: {
    trustClass: 'link-first',
    ticket: 'OLO-9.31',
    evidence: 'Graph email, no verified claim',
  },
  twitter: {
    trustClass: 'link-first',
    ticket: 'OLO-9.32',
    evidence: 'Email needs elevated API access and carries no verified claim',
  },
  reddit: {
    trustClass: 'link-only',
    ticket: 'OLO-9.33',
    evidence: 'No email address (`has_verified_email` alone names no address)',
  },
  spotify: {
    trustClass: 'link-first',
    ticket: 'OLO-9.34',
    evidence: '`/v1/me` email is documented as unverified',
  },
  twitch: {
    trustClass: 'trusted',
    ticket: 'OLO-9.35',
    evidence: '`email_verified` claim with the `user:read:email` scope',
  },
  tiktok: {
    trustClass: 'link-only',
    ticket: 'OLO-9.36',
    evidence: 'No email in user info',
  },
  roblox: {
    trustClass: 'link-only',
    ticket: 'OLO-9.37',
    evidence: 'Profile claims only, no email claim',
  },
  kick: {
    trustClass: 'link-first',
    ticket: 'OLO-9.38',
    evidence: '`/public/v1/users` email, no verified claim',
  },

  // ── Wave 3 — regional identity providers (OLO-9.39–9.44) ──────────────────────────────────────
  kakao: {
    trustClass: 'trusted',
    ticket: 'OLO-9.39',
    evidence: '`is_email_valid` and `is_email_verified` on `kakao_account`, both true',
  },
  naver: {
    trustClass: 'link-first',
    ticket: 'OLO-9.40',
    evidence: '`/v1/nid/me` email; verified semantics confirmed at implementation',
    provisional: true,
  },
  yandex: {
    trustClass: 'link-first',
    ticket: 'OLO-9.44',
    evidence: '`default_email`; verified semantics confirmed at implementation',
    provisional: true,
  },

  // ── Wave 4 — payments and creator platforms (OLO-9.45–9.49) ───────────────────────────────────
  paypal: {
    trustClass: 'trusted',
    ticket: 'OLO-9.45',
    evidence: '`email_verified` claim',
  },
  polar: {
    trustClass: 'link-first',
    ticket: 'OLO-9.46',
    evidence: 'Email and verified semantics confirmed at implementation',
    provisional: true,
  },
  patreon: {
    trustClass: 'trusted',
    ticket: 'OLO-9.47',
    evidence: '`is_email_verified` on the identity resource',
  },
  gumroad: {
    trustClass: 'link-first',
    ticket: 'OLO-9.48',
    evidence: 'User email, no verified claim',
  },
  paybin: {
    trustClass: 'link-first',
    ticket: 'OLO-9.49',
    evidence: 'Email semantics confirmed at implementation',
    provisional: true,
  },
};

/** Every sign-in provider slug in the catalog — the keys of {@link PROVIDER_TRUST_CLASSES}. */
export const CATALOG_PROVIDER_SLUGS: ReadonlySet<string> = new Set(
  Object.keys(PROVIDER_TRUST_CLASSES)
);

/**
 * The recorded trust class of a provider.
 *
 * @param provider A provider slug.
 * @returns The provider's class, or null for a slug outside the catalog (which is never trusted).
 */
export function providerTrustClass(provider: string): ProviderTrustClass | null {
  return Object.prototype.hasOwnProperty.call(PROVIDER_TRUST_CLASSES, provider)
    ? PROVIDER_TRUST_CLASSES[provider].trustClass
    : null;
}

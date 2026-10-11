/**
 * Installation sign-up policy (SGN-1.4, #5653).
 *
 * Mirrors `apiome-rest/tests/test_signup_policy.py` — both sides run the same matrix:
 *
 *   1. the pure policy (`signupRejectionCode`) and its normalizers;
 *   2. **each mode is enforced identically for email and every OAuth provider** — one table driven
 *      through `resolveAccountDecision` per provider and `resolveEmailSignupDecision` for the
 *      email form, then through the `resolveOAuthSignIn` orchestrator;
 *   3. the env fallback is unchanged when nothing is stored.
 */
import {
  AUTH_ERROR_CODES,
  AUTO_LINK_TRUSTED_PROVIDERS,
  resolveAccountDecision,
  resolveEmailSignupDecision,
  resolveOAuthSignIn,
  type ResolutionStore,
  type ResolutionUser,
} from '../lib/auth/account-resolution';
import {
  MAX_ALLOWED_EMAIL_DOMAINS,
  SIGNUP_MODES,
  SIGNUP_REJECTION_CODES,
  emailDomain,
  isSignupMode,
  normalizeEmailDomain,
  parseAllowedEmailDomains,
  signupPolicyFromEnv,
  signupPolicyFromRow,
  signupRejectionCode,
  type SignupMode,
  type SignupPolicy,
  type SignupRejectionCode,
} from '../lib/auth/signup-policy';

const OK_USER: ResolutionUser = { id: 'user-ok', enabled: true, verified: true };

const policy = (mode: SignupMode, allowedEmailDomains: string[] = []): SignupPolicy => ({
  mode,
  allowedEmailDomains,
  source: 'db',
});

/**
 * The sign-up paths the policy must treat identically: the email form plus every provider whose
 * verified email can reach account creation.
 */
const EMAIL_PATH = 'email';
const SIGNUP_PATHS = [EMAIL_PATH, ...Array.from(AUTO_LINK_TRUSTED_PROVIDERS).sort()];

/** [case, policy, address, expected rejection code — null when the account is created]. */
const POLICY_MATRIX: Array<[string, SignupPolicy, string, SignupRejectionCode | null]> = [
  ['open', policy('open'), 'ada@example.com', null],
  ['invite-only', policy('invite_only'), 'ada@example.com', 'signup-invite-only'],
  ['closed', policy('closed'), 'ada@example.com', 'signup-disabled'],
  ['open, domain allowed', policy('open', ['example.com']), 'ada@example.com', null],
  [
    'open, domain not allowed',
    policy('open', ['example.com']),
    'ada@elsewhere.test',
    'signup-domain-not-allowed',
  ],
  [
    'open, subdomain is not the listed domain',
    policy('open', ['example.com']),
    'ada@mail.example.com',
    'signup-domain-not-allowed',
  ],
  [
    'invite-only ignores the domain list',
    policy('invite_only', ['example.com']),
    'ada@example.com',
    'signup-invite-only',
  ],
  [
    'closed ignores the domain list',
    policy('closed', ['example.com']),
    'ada@example.com',
    'signup-disabled',
  ],
];

/** Run one sign-up attempt down the named path and return the decision. */
function decide(
  path: string,
  signupPolicy: SignupPolicy,
  email: string,
  emailUser: ResolutionUser | null = null,
) {
  if (path === EMAIL_PATH) return resolveEmailSignupDecision(email, signupPolicy, emailUser);
  return resolveAccountDecision({
    provider: path,
    providerUserId: 'prov-123',
    email,
    emailVerified: true,
    linkToUserId: null,
    identity: { found: false, user: null },
    emailUser,
    signupPolicy,
  });
}

// ---------------------------------------------------------------------------
// 1. Pure policy
// ---------------------------------------------------------------------------

describe('signupRejectionCode', () => {
  test.each(POLICY_MATRIX)('%s', (_case, signupPolicy, email, expected) => {
    expect(signupRejectionCode(signupPolicy, email)).toBe(expected);
  });

  test('a domain list refuses an address without a domain', () => {
    const restricted = policy('open', ['example.com']);
    expect(signupRejectionCode(restricted, null)).toBe('signup-domain-not-allowed');
    expect(signupRejectionCode(restricted, 'not-an-address')).toBe('signup-domain-not-allowed');
  });

  test('domain matching ignores case', () => {
    expect(signupRejectionCode(policy('open', ['example.com']), 'Ada@EXAMPLE.com')).toBeNull();
  });

  test('an unrecognized mode fails closed', () => {
    const odd = { ...policy('open'), mode: 'whatever' as SignupMode };
    expect(signupRejectionCode(odd, 'ada@example.com')).toBe('signup-disabled');
  });

  test('the rejection codes are members of the auth error contract', () => {
    expect(SIGNUP_REJECTION_CODES).toEqual({
      SIGNUP_DISABLED: AUTH_ERROR_CODES.SIGNUP_DISABLED,
      SIGNUP_INVITE_ONLY: AUTH_ERROR_CODES.SIGNUP_INVITE_ONLY,
      SIGNUP_DOMAIN_NOT_ALLOWED: AUTH_ERROR_CODES.SIGNUP_DOMAIN_NOT_ALLOWED,
    });
  });
});

describe('domain normalization', () => {
  test.each([
    ['example.com', 'example.com'],
    ['  Example.COM ', 'example.com'],
    ['@example.com', 'example.com'],
    ['mail.example.co.uk', 'mail.example.co.uk'],
  ])('accepts %j', (raw, expected) => {
    expect(normalizeEmailDomain(raw)).toBe(expected);
  });

  test.each([
    '',
    'localhost',
    'ada@example.com',
    '*.example.com',
    'https://example.com',
    'exa mple.com',
    '-bad.example.com',
    'example..com',
    42,
    null,
  ])('rejects %j', (raw) => {
    expect(normalizeEmailDomain(raw)).toBeNull();
  });

  test('parses a typed list: separators, duplicates and bad entries', () => {
    expect(parseAllowedEmailDomains('B.example, a.example\n@b.example  nope')).toEqual({
      domains: ['b.example', 'a.example'],
      invalid: ['nope'],
    });
    expect(parseAllowedEmailDomains('   ')).toEqual({ domains: [], invalid: [] });
  });

  test('reads the domain of an address', () => {
    expect(emailDomain(' Ada@Example.com ')).toBe('example.com');
    expect(emailDomain('@example.com')).toBeNull();
    expect(emailDomain('ada@')).toBeNull();
    expect(emailDomain(undefined)).toBeNull();
  });

  test('the list bound matches the REST and database bound', () => {
    expect(MAX_ALLOWED_EMAIL_DOMAINS).toBe(200);
  });
});

// ---------------------------------------------------------------------------
// 2. Identical enforcement for email and every OAuth provider
// ---------------------------------------------------------------------------

describe('every sign-up path enforces the policy identically', () => {
  const cases = POLICY_MATRIX.flatMap(([name, signupPolicy, email, expected]) =>
    SIGNUP_PATHS.map((path) => [`${path}: ${name}`, path, signupPolicy, email, expected] as const),
  );

  test.each(cases)('%s', (_label, path, signupPolicy, email, expected) => {
    const decision = decide(path, signupPolicy, email);
    expect(decision).toEqual(
      expected === null ? { action: 'signup', email } : { action: 'reject', code: expected },
    );
  });

  const existing = SIGNUP_PATHS.flatMap((path) =>
    SIGNUP_MODES.map((mode) => [path, mode] as const),
  );

  test.each(existing)('%s under %s never blocks an existing account', (path, mode) => {
    const decision = decide(path, policy(mode, ['other.test']), 'ada@example.com', OK_USER);
    expect(decision).toEqual({
      action: path === EMAIL_PATH ? 'sign-in' : 'auto-link',
      user: OK_USER,
    });
  });

  test('an email sign-up needs an address', () => {
    expect(resolveEmailSignupDecision('  ', policy('open'))).toEqual({
      action: 'reject',
      code: AUTH_ERROR_CODES.EMAIL_REQUIRED,
    });
  });

  test('the policy supersedes the legacy signupDisabled fact', () => {
    const decision = resolveAccountDecision({
      provider: 'github',
      providerUserId: 'prov-123',
      email: 'ada@example.com',
      emailVerified: true,
      linkToUserId: null,
      identity: { found: false, user: null },
      emailUser: null,
      signupDisabled: true,
      signupPolicy: policy('open'),
    });
    expect(decision.action).toBe('signup');
  });
});

describe('resolveOAuthSignIn reads the policy from the store', () => {
  /** A store with no identity and no account for the address, serving the given policy. */
  function makeStore(signupPolicy?: SignupPolicy) {
    const getSignupPolicy = jest.fn(async () => signupPolicy as SignupPolicy);
    const createPendingSignup = jest.fn(async () => ({ id: 'pending-1' }));
    const store: ResolutionStore = {
      getIdentity: async () => ({ found: false, userId: null }),
      getUserById: async () => null,
      getUserByEmail: async () => null,
      linkIdentity: async () => ({ success: true }),
      recordIdentityLogin: async () => undefined,
      recordUserLogin: async () => undefined,
      createPendingSignup,
      ...(signupPolicy ? { getSignupPolicy } : {}),
    };
    return { store, getSignupPolicy, createPendingSignup };
  }

  const payload = (email = 'ada@example.com') => ({
    user: { email, name: 'Ada' },
    account: { providerAccountId: 'prov-123' },
    profile: { email, email_verified: true },
  });

  test.each([
    ['closed', policy('closed'), '/login?error=signup-disabled'],
    ['invite_only', policy('invite_only'), '/login?error=signup-invite-only'],
    [
      'open + other domain',
      policy('open', ['corp.example']),
      '/login?error=signup-domain-not-allowed',
    ],
  ])('%s refuses a new account and stores nothing', async (_name, signupPolicy, expected) => {
    const { store, createPendingSignup } = makeStore(signupPolicy);
    expect(await resolveOAuthSignIn('github', payload(), null, store)).toBe(expected);
    expect(createPendingSignup).not.toHaveBeenCalled();
  });

  test('open routes a new account to the sign-up wizard', async () => {
    const { store } = makeStore(policy('open', ['example.com']));
    expect(await resolveOAuthSignIn('github', payload(), null, store)).toBe(
      '/signup/oauth?token=pending-1',
    );
  });

  test('the policy is not read for an existing account', async () => {
    const { store, getSignupPolicy } = makeStore(policy('closed'));
    store.getUserByEmail = async () => OK_USER;
    expect(await resolveOAuthSignIn('github', payload(), null, store)).toBe(true);
    expect(getSignupPolicy).not.toHaveBeenCalled();
  });

  test('a store without a policy reader keeps the env fallback', async () => {
    const previous = process.env.AUTH_SIGNUP_DISABLED;
    try {
      delete process.env.AUTH_SIGNUP_DISABLED;
      expect(await resolveOAuthSignIn('github', payload(), null, makeStore().store)).toBe(
        '/signup/oauth?token=pending-1',
      );
      process.env.AUTH_SIGNUP_DISABLED = '1';
      expect(await resolveOAuthSignIn('github', payload(), null, makeStore().store)).toBe(
        '/login?error=signup-disabled',
      );
    } finally {
      if (previous === undefined) delete process.env.AUTH_SIGNUP_DISABLED;
      else process.env.AUTH_SIGNUP_DISABLED = previous;
    }
  });
});

// ---------------------------------------------------------------------------
// 3. Env fallback and stored rows
// ---------------------------------------------------------------------------

describe('env fallback', () => {
  test.each([
    ['true', 'closed'],
    [' TRUE ', 'closed'],
    ['1', 'closed'],
    ['false', 'open'],
    ['0', 'open'],
    ['yes', 'open'],
    [undefined, 'open'],
  ])('AUTH_SIGNUP_DISABLED=%j reads as %s', (value, mode) => {
    expect(signupPolicyFromEnv({ AUTH_SIGNUP_DISABLED: value })).toEqual({
      mode,
      allowedEmailDomains: [],
      source: 'env',
    });
  });
});

describe('signupPolicyFromRow', () => {
  test('no row, or an unrecognized mode, is unusable', () => {
    expect(signupPolicyFromRow(null)).toBeNull();
    expect(signupPolicyFromRow({ mode: 'nonsense' })).toBeNull();
    expect(isSignupMode('invite_only')).toBe(true);
    expect(isSignupMode('invite-only')).toBe(false);
  });

  test('normalizes stored domains and drops malformed ones', () => {
    expect(
      signupPolicyFromRow({
        mode: 'open',
        allowed_email_domains: ['Example.com', 'not a domain', 'example.com'],
      }),
    ).toEqual({ mode: 'open', allowedEmailDomains: ['example.com'], source: 'db' });
  });
});

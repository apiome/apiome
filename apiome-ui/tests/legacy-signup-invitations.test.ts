/**
 * Retiring the legacy sign-up request queue (SGN-1.3, #5652): the one-time invitation sweep, its
 * email, its ledger queries, and the guarantee that nothing writes `apiome.signup` any more.
 */
import fs from 'fs';
import path from 'path';

import { jest } from '@jest/globals';

import {
  inviteLegacySignupRequesters,
  type LegacySignupInvitationDeps,
} from '../lib/auth/legacy-signup-invitations';
import { buildLegacySignupInvitationEmail, type SignupEmailMessage } from '../lib/auth/email-signup';
import type { SignupPolicy } from '../lib/auth/signup-policy';

const mockQuery = jest.fn<(sql: string, params?: unknown[]) => Promise<unknown>>();
jest.mock('../lib/db/db', () => ({ query: (...args: [string, unknown[]?]) => mockQuery(...args) }));

const CONFIGURED = {
  SENDGRID_API_KEY: 'SG.key',
  EMAIL_FROM: 'Apiome <no-reply@apiome.dev>',
  BETTER_AUTH_URL: 'https://app.apiome.dev/',
};

const OPEN: SignupPolicy = { mode: 'open', allowedEmailDomains: [], source: 'db' };

/** In-memory seams: a queue, a ledger, a set of existing accounts and a mailbox. */
function fakeDeps(overrides: Partial<LegacySignupInvitationDeps> = {}) {
  const ledger = new Map<string, string>();
  const outbox: Array<{ to: string; message: SignupEmailMessage }> = [];
  const deps: LegacySignupInvitationDeps = {
    listPending: async () => [
      { emailAddress: 'Tomas.Berg@northwind.io', name: 'Tomas Berg' },
      { emailAddress: 'aiko@harbor-labs.com', name: 'Aiko Tanaka' },
    ],
    claim: async (email, outcome) => {
      if (ledger.has(email)) return false;
      ledger.set(email, outcome);
      return true;
    },
    release: async (email) => {
      ledger.delete(email);
    },
    accountExists: async () => false,
    resolvePolicy: async () => OPEN,
    send: async (to, message) => {
      outbox.push({ to, message });
      return true;
    },
    env: CONFIGURED,
    ...overrides,
  };
  return { deps, ledger, outbox };
}

describe('inviteLegacySignupRequesters', () => {
  it('does nothing without a mail sender or base URL', async () => {
    const listPending = jest.fn(async () => []);
    for (const env of [{}, { ...CONFIGURED, SENDGRID_API_KEY: '' }, { ...CONFIGURED, BETTER_AUTH_URL: '' }]) {
      const { deps } = fakeDeps({ env, listPending });
      expect(await inviteLegacySignupRequesters(deps)).toBeNull();
    }
    expect(listPending).not.toHaveBeenCalled();
  });

  it('emails each queued requester once, to the canonical address, with a link to /signup', async () => {
    const { deps, ledger, outbox } = fakeDeps();
    const summary = await inviteLegacySignupRequesters(deps);

    expect(summary).toMatchObject({ sent: 2, failed: 0, accountExists: 0 });
    expect(outbox.map((m) => m.to)).toEqual(['tomas.berg@northwind.io', 'aiko@harbor-labs.com']);
    expect(outbox[0].message.subject).toBe('Finish creating your Apiome account');
    expect(outbox[0].message.text).toContain('Hello Tomas Berg,');
    expect(outbox[0].message.text).toContain('https://app.apiome.dev/signup');
    // The ledger is keyed by the address exactly as the queue holds it.
    expect([...ledger.entries()]).toEqual([
      ['Tomas.Berg@northwind.io', 'sent'],
      ['aiko@harbor-labs.com', 'sent'],
    ]);

    // A second run (the next server start) finds them handled.
    const again = await inviteLegacySignupRequesters({ ...deps, listPending: async () => [] });
    expect(again?.sent).toBe(0);
  });

  it('records an address that already has an account without emailing it', async () => {
    const { deps, ledger, outbox } = fakeDeps({
      accountExists: async (email) => email === 'aiko@harbor-labs.com',
    });
    const summary = await inviteLegacySignupRequesters(deps);
    expect(summary).toMatchObject({ sent: 1, accountExists: 1 });
    expect(outbox.map((m) => m.to)).toEqual(['tomas.berg@northwind.io']);
    expect(ledger.get('aiko@harbor-labs.com')).toBe('account_exists');
  });

  it('leaves addresses the sign-up policy refuses unrecorded, so a later start can invite them', async () => {
    const { deps, ledger, outbox } = fakeDeps({
      resolvePolicy: async () => ({ mode: 'open', allowedEmailDomains: ['northwind.io'], source: 'db' }),
    });
    const summary = await inviteLegacySignupRequesters(deps);
    expect(summary).toMatchObject({ sent: 1, refusedByPolicy: 1 });
    expect(outbox.map((m) => m.to)).toEqual(['tomas.berg@northwind.io']);
    expect(ledger.has('aiko@harbor-labs.com')).toBe(false);

    const closed = fakeDeps({ resolvePolicy: async () => ({ ...OPEN, mode: 'closed' }) });
    expect(await inviteLegacySignupRequesters(closed.deps)).toMatchObject({ sent: 0, refusedByPolicy: 2 });
    expect(closed.outbox).toHaveLength(0);
  });

  it('releases the claim when the send fails', async () => {
    const { deps, ledger } = fakeDeps({ send: async () => false });
    const summary = await inviteLegacySignupRequesters(deps);
    expect(summary).toMatchObject({ sent: 0, failed: 2 });
    expect(ledger.size).toBe(0);
  });

  it('skips an address another replica claimed first', async () => {
    const send = jest.fn(async () => true);
    const { deps } = fakeDeps({ claim: async () => false, send });
    expect(await inviteLegacySignupRequesters(deps)).toMatchObject({ sent: 0, claimedElsewhere: 2 });
    expect(send).not.toHaveBeenCalled();
  });

  it('skips a queued row whose address is not a usable email', async () => {
    const { deps, outbox } = fakeDeps({
      listPending: async () => [{ emailAddress: 'not-an-email', name: 'X' }],
    });
    expect(await inviteLegacySignupRequesters(deps)).toMatchObject({ invalid: 1, sent: 0 });
    expect(outbox).toHaveLength(0);
  });
});

describe('buildLegacySignupInvitationEmail', () => {
  it('escapes the name in the HTML body and falls back to a plain greeting', () => {
    const message = buildLegacySignupInvitationEmail({
      name: '<b>Eve</b>',
      signupUrl: 'https://app.apiome.dev/signup',
    });
    expect(message.html).toContain('&lt;b&gt;Eve&lt;/b&gt;');
    expect(message.html).not.toContain('<b>Eve</b>');
    expect(message.html).toContain('Create your account');
    expect(buildLegacySignupInvitationEmail({ name: '  ', signupUrl: 'x' }).text).toMatch(/^Hello,/);
  });

  it('asks for a new password rather than reusing the queued one', () => {
    const { text } = buildLegacySignupInvitationEmail({ signupUrl: 'https://app.apiome.dev/signup' });
    expect(text).toContain('choose a password');
  });
});

describe('legacy-signup-invitation ledger queries', () => {
  // Required lazily so the db mock above is in place.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ledger = require('../lib/db/legacy-signup-invitation');

  beforeEach(() => mockQuery.mockReset());

  it('lists queued requests with no ledger row', async () => {
    mockQuery.mockResolvedValue({ rows: [{ email_address: 'a@b.io', name: 'A' }] });
    expect(await ledger.listUninvitedLegacySignups()).toEqual([{ emailAddress: 'a@b.io', name: 'A' }]);
    expect(mockQuery.mock.calls[0][0]).toContain('FROM apiome.signup');
    expect(mockQuery.mock.calls[0][0]).toContain('NOT EXISTS');
  });

  it('reads a missing table as an empty queue', async () => {
    mockQuery.mockRejectedValue(Object.assign(new Error('missing'), { code: '42P01' }));
    expect(await ledger.listUninvitedLegacySignups()).toEqual([]);
    mockQuery.mockRejectedValue(Object.assign(new Error('down'), { code: '57P01' }));
    await expect(ledger.listUninvitedLegacySignups()).rejects.toThrow('down');
  });

  it('claims with ON CONFLICT DO NOTHING and reports who won', async () => {
    mockQuery.mockResolvedValueOnce({ rowCount: 1 }).mockResolvedValueOnce({ rowCount: 0 });
    expect(await ledger.claimLegacySignupInvitation('a@b.io', 'sent')).toBe(true);
    expect(await ledger.claimLegacySignupInvitation('a@b.io', 'sent')).toBe(false);
    expect(mockQuery.mock.calls[0][0]).toContain('ON CONFLICT (email_address) DO NOTHING');
    expect(mockQuery.mock.calls[0][1]).toEqual(['a@b.io', 'sent']);
  });

  it('releases only a sent claim', async () => {
    mockQuery.mockResolvedValue({ rowCount: 1 });
    await ledger.releaseLegacySignupInvitation('a@b.io');
    expect(mockQuery.mock.calls[0][0]).toContain("outcome = 'sent'");
  });
});

describe('the queue is retired (source level)', () => {
  const root = path.resolve(__dirname, '..');

  /** Every .ts/.tsx file under a directory. */
  const sources = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : sources(full);
      return /\.tsx?$/.test(entry.name) ? [full] : [];
    });

  it('no app code writes apiome.signup', () => {
    const writers = [...sources(path.join(root, 'lib')), ...sources(path.join(root, 'src'))].filter((file) =>
      /(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE)\s+apiome\.signup\b(?!_)/i.test(fs.readFileSync(file, 'utf8'))
    );
    expect(writers).toEqual([]);
  });

  it('the request and approval actions are gone', () => {
    const helper = fs.readFileSync(path.join(root, 'lib/db/helper.ts'), 'utf8');
    const admin = fs.readFileSync(path.join(root, 'lib/db/admin-helper.ts'), 'utf8');
    expect(helper).not.toContain('createSignupRequest');
    for (const name of ['getAllSignups', 'getSignupStats', 'createUserFromSignup', 'deleteSignup']) {
      expect(admin).not.toContain(name);
    }
  });

  it('server startup runs the invitation sweep', () => {
    const instrumentation = fs.readFileSync(path.join(root, 'src/instrumentation.ts'), 'utf8');
    expect(instrumentation).toContain("import('../lib/auth/legacy-signup-invitations')");
    expect(instrumentation).toContain('runLegacySignupInvitations()');
  });
});

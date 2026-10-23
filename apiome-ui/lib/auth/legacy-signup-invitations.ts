/**
 * Invite the people left in the retired sign-up request queue (SGN-1.3, #5652).
 *
 * The admin console's "approve a sign-up request" flow is gone (it leaked whether an address was
 * queued, #4962, and created verified accounts from unconfirmed passwords). Anyone still waiting in
 * `apiome.signup` gets one email telling them to create the account themselves on /signup, which
 * runs the normal email sign-up (SGN-1.1) and its confirmation link.
 *
 * Runs once per server start from `src/instrumentation.ts`, and only when email sign-up can run
 * (a mail sender and the public base URL). For each queued address with no ledger row:
 *
 * - **already has an account** → recorded as `account_exists`, nothing sent;
 * - **refused by the sign-up policy** (closed, invite-only, domain not allowed) → left unrecorded,
 *   so a later start invites it if sign-up opens before the queue is dropped;
 * - otherwise → claimed as `sent` and emailed; a failed send releases the claim for the next start.
 *
 * Server-only: reads the database and sends mail. Never import from a client component.
 */

import { resolveEmailSignupDecision } from './account-resolution';
import {
  SIGNUP_PATH,
  buildLegacySignupInvitationEmail,
  canonicalSignupEmail,
  isEmailSignupAvailable,
  publicBaseUrl,
  type SignupEmailMessage,
} from './email-signup';
import type { SignupPolicy } from './signup-policy';
import type {
  LegacySignupInvitationOutcome,
  LegacySignupRequest,
} from '../db/legacy-signup-invitation';

/** What one sweep did, for the startup log. Addresses are never logged. */
export interface LegacySignupInvitationSummary {
  /** Invitations SendGrid accepted. */
  sent: number;
  /** Queued addresses that already had an account (recorded, nothing sent). */
  accountExists: number;
  /** Addresses the sign-up policy refuses today (left for a later start). */
  refusedByPolicy: number;
  /** Rows whose address is not a usable email (left untouched). */
  invalid: number;
  /** Sends that failed (claim released for a later start). */
  failed: number;
  /** Addresses another replica claimed first. */
  claimedElsewhere: number;
}

/** Everything the sweep touches; injected so it is unit-tested without a database or SendGrid. */
export interface LegacySignupInvitationDeps {
  /** Queued requests with no ledger row. */
  listPending: () => Promise<LegacySignupRequest[]>;
  /** Atomically record an outcome; `false` when the address was already handled. */
  claim: (emailAddress: string, outcome: LegacySignupInvitationOutcome) => Promise<boolean>;
  /** Drop a `sent` claim whose email failed. */
  release: (emailAddress: string) => Promise<void>;
  /** Whether a live account already holds the canonical address. */
  accountExists: (canonicalEmail: string) => Promise<boolean>;
  /** The effective installation sign-up policy. */
  resolvePolicy: () => Promise<SignupPolicy>;
  /** Send one email; `true` once accepted. */
  send: (to: string, message: SignupEmailMessage) => Promise<boolean>;
  /** Environment map (mail sender and base URL). */
  env: NodeJS.Dict<string>;
}

/** An all-zero summary. */
const emptySummary = (): LegacySignupInvitationSummary => ({
  sent: 0,
  accountExists: 0,
  refusedByPolicy: 0,
  invalid: 0,
  failed: 0,
  claimedElsewhere: 0,
});

/**
 * Invite every queued requester that has not been handled yet.
 *
 * @param deps The data, policy and mail seams (see {@link defaultLegacySignupInvitationDeps}).
 * @returns The counts, or `null` when email sign-up is not configured and nothing was attempted.
 */
export async function inviteLegacySignupRequesters(
  deps: LegacySignupInvitationDeps
): Promise<LegacySignupInvitationSummary | null> {
  const baseUrl = publicBaseUrl(deps.env);
  if (!isEmailSignupAvailable(deps.env) || !baseUrl) return null;

  const pending = await deps.listPending();
  const summary = emptySummary();
  if (pending.length === 0) return summary;

  const policy = await deps.resolvePolicy();
  const signupUrl = `${baseUrl}${SIGNUP_PATH}`;

  for (const request of pending) {
    const canonical = canonicalSignupEmail(request.emailAddress);
    if (!canonical) {
      summary.invalid += 1;
      continue;
    }

    if (await deps.accountExists(canonical)) {
      if (await deps.claim(request.emailAddress, 'account_exists')) summary.accountExists += 1;
      else summary.claimedElsewhere += 1;
      continue;
    }

    if (resolveEmailSignupDecision(canonical, policy, null).action === 'reject') {
      summary.refusedByPolicy += 1;
      continue;
    }

    if (!(await deps.claim(request.emailAddress, 'sent'))) {
      summary.claimedElsewhere += 1;
      continue;
    }
    const message = buildLegacySignupInvitationEmail({ name: request.name, signupUrl });
    if (await deps.send(canonical, message)) {
      summary.sent += 1;
    } else {
      summary.failed += 1;
      await deps.release(request.emailAddress);
    }
  }
  return summary;
}

/**
 * The production seams: the V314 ledger, the account lookup, the cached policy and SendGrid.
 *
 * Loaded lazily so importing this module (and its tests) never opens the database pool.
 *
 * @returns The dependencies for {@link inviteLegacySignupRequesters}.
 */
export async function defaultLegacySignupInvitationDeps(): Promise<LegacySignupInvitationDeps> {
  const [ledger, verification, resolver, mail] = await Promise.all([
    import('../db/legacy-signup-invitation'),
    import('../db/email-verification'),
    import('./signup-policy-resolver'),
    import('./send-signup-email'),
  ]);
  return {
    listPending: ledger.listUninvitedLegacySignups,
    claim: ledger.claimLegacySignupInvitation,
    release: ledger.releaseLegacySignupInvitation,
    accountExists: async (email) => (await verification.findSignupAccount(email)) !== null,
    resolvePolicy: () => resolver.resolveSignupPolicy(),
    send: (to, message) => mail.sendSignupEmail(to, message),
    env: process.env,
  };
}

/**
 * The startup entry point: run the sweep and log its counts; never throws.
 *
 * @returns Resolves when the sweep is done (or has failed and been logged).
 */
export async function runLegacySignupInvitations(): Promise<void> {
  // Checked before the seams load, so an installation without mail never touches the database.
  if (!isEmailSignupAvailable()) return;
  try {
    const summary = await inviteLegacySignupRequesters(await defaultLegacySignupInvitationDeps());
    if (summary && Object.values(summary).some((count) => count > 0)) {
      console.info('[legacy-signup] invited queued sign-up requesters', summary);
    }
  } catch (error) {
    console.error(
      '[legacy-signup] invitation sweep failed',
      error instanceof Error ? error.name : 'unknown'
    );
  }
}

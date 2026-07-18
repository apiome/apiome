/**
 * Display model of the Free license shown by the first-tenant onboarding
 * wizard's summary step (OLO-4.1, #4205).
 *
 * The values mirror what provisioning actually grants: the free-tier
 * entitlements seeded by `insertFreeTierEntitlements` (`lib/db/oauth-signup.ts`
 * — 1 tenant, 1 project, 3 versions) plus the curated sample project. Once the
 * license REST surface lands (OLO-5.4, `GET /v1/tenants/{slug}/license`) this
 * constant should be replaced by live plan data.
 */

/** One quota line of the plan summary. */
export interface FreeLicenseLimit {
  /** Human-readable name of the quota (e.g. "Projects"). */
  label: string;
  /** Granted amount, as display text (e.g. "1"). */
  value: string;
}

/** Static description of the Free plan for pre-confirmation display. */
export interface FreeLicenseSummary {
  /** Plan name as shown on the summary card. */
  planName: string;
  /** One-line explanation of what being on this plan means. */
  description: string;
  /** Quota lines granted by the plan. */
  limits: readonly FreeLicenseLimit[];
  /** Non-quota extras included with the plan. */
  includes: readonly string[];
}

/** The Free plan every first tenant is created on. */
export const FREE_LICENSE_SUMMARY: FreeLicenseSummary = {
  planName: 'Free',
  description:
    'Your organization starts on the Free plan — no payment details required.',
  limits: [
    { label: 'Tenants', value: '1' },
    { label: 'Projects', value: '1' },
    { label: 'API versions per project', value: '3' },
  ],
  includes: ['Curated sample project so your workspace is not empty'],
};

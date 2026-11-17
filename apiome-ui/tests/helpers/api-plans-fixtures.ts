/**
 * API plan fixtures shared by the product-editor and plans suites (APX-1.2, #6099), so the docs
 * screenshots `api-product-editor` and `api-plan-editor` show the same Payments plans.
 */

import type { ApiPlan, PlanEnvironment } from '../../lib/api-plans';
import type { GatewayConfig } from '../../lib/gateway-configs';

/** A Kong control plane the workspace's Kong connector reported. */
export const PROD_ENV: PlanEnvironment = {
  id: 'g-prod',
  slug: 'kong-prod-cp',
  name: 'Kong · prod-cp',
  environment: 'prod-cp',
  connector_kind: 'kong-admin',
  can_provision: false,
  missing: false,
};

/**
 * One plan, with overrides.
 *
 * @param overrides - Fields to change.
 * @returns The plan.
 */
export function plan(overrides: Partial<ApiPlan> = {}): ApiPlan {
  return {
    id: 'pl-standard',
    product: 'payments',
    slug: 'standard',
    name: 'Standard',
    description: 'For production traffic.',
    auth_strategy: 'key_auth',
    auth_config: { header_name: 'X-API-Key' },
    limits: [
      { window: 'minute', requests: 100 },
      { window: 'day', requests: 50000 },
    ],
    concurrency: null,
    approval: 'manual',
    environments: [PROD_ENV],
    declared_only: true,
    credential_ttl_days: 90,
    terms_url: 'https://example.com/terms',
    pricing_note: '$49 a month',
    billing_ref: 'price_standard',
    state: 'published',
    accepts_subscriptions: true,
    deprecated_at: null,
    retire_at: null,
    retired_at: null,
    deprecation_message: null,
    successor: null,
    owners_notified_at: null,
    notices: [
      {
        code: 'api-plan-declared-only',
        message:
          'Declared only: kong-prod-cp cannot be provisioned yet (its connector has no provisioning), so Apiome records the plan but changes nothing on the gateway.',
      },
    ],
    warnings: [
      {
        code: 'api-plan-auth-mismatch',
        message: "Refunds API declares no API key scheme, so this plan's auth does not match it.",
        member: { kind: 'project_version', ref: 'r-2', name: 'Refunds API' },
      },
    ],
    created_by: null,
    created_at: null,
    updated_at: '2026-11-16T10:00:00Z',
    ...overrides,
  };
}

/** The Payments plans: a sandbox tier and the standard tier. */
export const PLANS: ApiPlan[] = [
  plan({
    id: 'pl-sandbox',
    slug: 'sandbox',
    name: 'Sandbox',
    description: 'Try the API.',
    auth_config: {},
    limits: [{ window: 'minute', requests: 10 }],
    approval: 'auto',
    environments: [],
    credential_ttl_days: null,
    terms_url: null,
    pricing_note: 'Free',
    billing_ref: null,
    notices: [
      {
        code: 'api-plan-declared-only',
        message: 'Declared only: the plan names no gateway environment, so Apiome records its limits but provisions nothing.',
      },
    ],
  }),
  plan(),
];

/** The workspace's gateway configs, as `/api/gateway-configs` returns them. */
export const GATEWAYS: Partial<GatewayConfig>[] = [
  { id: 'g-prod', slug: 'kong-prod-cp', name: 'Kong · prod-cp', connector: { id: 'c-1', name: 'Kong', kind: 'kong-admin' } },
  { id: 'g-stage', slug: 'kong-staging-cp', name: 'Kong · staging-cp', connector: { id: 'c-1', name: 'Kong', kind: 'kong-admin' } },
];

/**
 * APX-1.4 (#6101): the Payments plans with **Standard** deprecated — retiring on 31 March 2027, its
 * consumers moving to a new **Premium** tier — for the lifecycle tests and the `api-plan-editor`
 * screenshot (deprecate / migrate states).
 */
export const DEPRECATED_PLANS: ApiPlan[] = [
  PLANS[0],
  plan({
    state: 'deprecated',
    accepts_subscriptions: false,
    deprecated_at: '2026-11-16T10:00:00+00:00',
    retire_at: '2027-03-31T00:00:00+00:00',
    deprecation_message: 'Standard retires on 31 March 2027. Move to Premium; your key keeps working.',
    successor: { slug: 'premium', name: 'Premium', state: 'published' },
    owners_notified_at: '2026-11-16T10:00:00+00:00',
    notices: [
      PLANS[1].notices[0],
      {
        code: 'api-plan-deprecated',
        message:
          'Deprecated: new subscriptions are blocked. It retires on 2027-03-31. Consumers move to Premium (premium).',
      },
    ],
  }),
  plan({
    id: 'pl-premium',
    slug: 'premium',
    name: 'Premium',
    description: 'Higher limits for production traffic.',
    limits: [
      { window: 'minute', requests: 500 },
      { window: 'day', requests: 250000 },
    ],
    pricing_note: '$149 a month',
    billing_ref: 'price_premium',
    warnings: [],
  }),
];

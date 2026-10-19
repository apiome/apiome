/**
 * Gateway configs in the UI — CDG-5.3 (#5981).
 *
 * The wire shapes of `GET /v1/tenants/{t}/gateway-configs[/{slug}]`, the page that renders one, and
 * what the push-back action may do. A gateway config is one (connector, environment); its posture
 * is names and schemes only, never a credential.
 */

import type { EntityOwner } from '@lib/owners';

/** An auth scheme and the plugin or policy that enforces it. */
export interface GatewayAuth {
  scheme: string;
  via: string;
}

/** Auth and rate-limit posture. */
export interface GatewayPosture {
  auth: GatewayAuth[];
  rateLimits: Array<{ name: string; kind: string }>;
  policies: string[];
  credentialRedactions: number;
}

/** One API the environment serves. */
export interface GatewayServedApi {
  itemId: string;
  name: string;
  remoteId: string | null;
  status: string;
  hosts: string[];
  basePath: string | null;
  projectId: string | null;
  projectName: string | null;
  /** `true` for a Project, `false` for a catalog item, `null` when not imported. */
  publishable: boolean | null;
  lastSeenAt: string | null;
}

/** Whether a catalog item can be pushed back to this gateway's format. */
export interface GatewayPushBack {
  /** The export target (`kong`), or `null`. */
  target: string | null;
  /** Why not: `fmt-7.7` or `unsupported`. */
  reason: string | null;
}

/** A gateway config. */
export interface GatewayConfig {
  id: string;
  slug: string;
  name: string;
  connector: { id: string; name: string; kind: string };
  environment: string;
  flavor: string;
  apiCount: number;
  posture: GatewayPosture;
  declaredLosses: Array<{ construct: string; reason: string }>;
  pushBack: GatewayPushBack;
  owner: EntityOwner | null;
  apis: GatewayServedApi[];
  lastSyncedAt: string | null;
  updatedAt: string | null;
}

/** The page of one gateway config. */
export function gatewayConfigHref(slug: string): string {
  return `/ade/dashboard/connectors/environments/${encodeURIComponent(slug)}`;
}

/** The FMT-7.7 issue the AWS, Azure APIM and Apigee emit modes wait on. */
export const FMT_7_7_ISSUE = 'https://github.com/apiome/apiome/issues/5461';

/**
 * Why push-back is not offered, in words, or `null` when it is.
 *
 * @param pushBack - The gateway config's push-back.
 */
export function pushBackUnavailable(pushBack: GatewayPushBack): string | null {
  if (pushBack.target) return null;
  if (pushBack.reason === 'fmt-7.7') return 'Push back to this gateway needs its emit mode (FMT-7.7, #5461).';
  return 'This connector has no gateway format to push back to.';
}

/** Where a served API lives in the app, or `null` when it was not imported. */
export function servedApiHref(api: GatewayServedApi): string | null {
  if (!api.projectId) return null;
  return api.publishable
    ? `/ade/dashboard/versions?projectId=${encodeURIComponent(api.projectId)}`
    : `/ade/dashboard/catalog/${encodeURIComponent(api.projectId)}`;
}

/** A slug or id, as the read accepts. */
const REF = /^([a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?|[0-9a-fA-F-]{36})$/;

/**
 * The REST path (below `/v1/tenants/{slug}`) a proxy GET may reach, or `null`.
 *
 * @param segments - The path segments after `/api/gateway-configs`.
 */
export function gatewayConfigProxyPath(segments: readonly string[]): string | null {
  if (segments.length === 0) return 'gateway-configs';
  if (segments.length === 1 && REF.test(segments[0])) return `gateway-configs/${encodeURIComponent(segments[0])}`;
  return null;
}

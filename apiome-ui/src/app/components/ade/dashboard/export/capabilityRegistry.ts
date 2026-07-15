/**
 * Destination capability & technical-documentation registry contract (EFP-1.2, #4811).
 *
 * The REST `GET /api/export/{tenant}/capability-registry` endpoint returns the versioned
 * destination capability registry: one reviewed capability entry per registered export
 * destination (label, availability state, and host-allowlisted destination-format
 * documentation with a safe fallback) plus the reviewed explanation for every projection
 * reason code. This module mirrors those Python models field-for-field so the response
 * deserialises directly, and adds the pure guards the export UI (EFP-2.3's evidence drawer)
 * needs to render only *trustworthy* data:
 *
 * - `isKnownReasonCode` / `assertKnownReasonCode` — reject any reason code outside the
 *   canonical taxonomy, so a manifest edge or a drawer never renders an unknown category;
 * - `isSafeDocumentationUrl` / `assertSafeDocumentationUrl` — mirror the Python host
 *   allowlist so the UI never turns an unsafe or off-allowlist URL into a link;
 * - `sanitizeDocumentationEvidence` — drop an unsafe URL to the truthful
 *   "documentation unavailable" fallback rather than rendering it;
 * - `validateRegistrySnapshot` — a whole-snapshot contract check the UI/tests run to reject
 *   a registry that carries an unknown reason code or an unsafe link.
 *
 * Everything here is pure (no React, no fetch) so it can be unit-tested directly — mirroring
 * `./exportTargetCatalog.ts`. Keep `REASON_CODES` and `ALLOWED_DOCUMENTATION_HOSTS` in sync
 * with `apiome-rest/src/app/{projection_taxonomy,capability_registry}.py`.
 */

/** A projection reason code (mirrors Python `ProjectionReason`). */
export type ProjectionReasonCode =
  | 'destination_unsupported'
  | 'emitter_unsupported'
  | 'source_incomplete'
  | 'source_parse_limit'
  | 'option_excluded'
  | 'security_redacted'
  | 'target_tool_unavailable'
  | 'not_applicable';

/** Whether a destination emitter is available in the runtime (mirrors Python `DestinationAvailability`). */
export type DestinationAvailability = 'available' | 'experimental' | 'unavailable';

/**
 * The canonical set of valid reason-code strings (mirrors Python `REASON_CODES`).
 *
 * The single source of truth for what a valid reason code is on the UI side; the contract
 * guards below reject anything outside it.
 */
export const REASON_CODES: readonly ProjectionReasonCode[] = [
  'destination_unsupported',
  'emitter_unsupported',
  'source_incomplete',
  'source_parse_limit',
  'option_excluded',
  'security_redacted',
  'target_tool_unavailable',
  'not_applicable',
];

const REASON_CODE_SET: ReadonlySet<string> = new Set(REASON_CODES);

/**
 * Authoritative documentation hosts the UI is allowed to link to (mirrors Python
 * `ALLOWED_DOCUMENTATION_HOSTS`).
 *
 * An exact, lowercased host match is required — no subdomain wildcards, no ports, no
 * credentials — so a look-alike host is rejected. Kept identical to the backend allowlist so
 * a URL the backend accepted is the only kind the UI will render.
 */
export const ALLOWED_DOCUMENTATION_HOSTS: ReadonlySet<string> = new Set([
  'spec.openapis.org',
  'www.asyncapi.com',
  'spec.graphql.org',
  'protobuf.dev',
  'avro.apache.org',
  'json-schema.org',
  'datatracker.ietf.org',
  'www.w3.org',
  'cloudevents.io',
  'smithy.io',
  'typespec.io',
  'www.odata.org',
  'www.hl7.org',
  'capnproto.org',
  'thrift.apache.org',
  'flatbuffers.dev',
  'connectrpc.com',
  'spec.open-rpc.org',
  'learning.postman.com',
  'raml.org',
  'apiblueprint.org',
  'www.omg.org',
  'www.itu.int',
  'www.iso20022.org',
  'www.fixtrading.org',
]);

/** Reviewed destination-format documentation metadata (mirrors Python `DocumentationEvidence`). */
export interface DocumentationEvidence {
  /** Human label of the destination specification (e.g. `"OpenAPI 3.1"`). */
  specification?: string | null;
  /** Specification version the link refers to, when versioned. */
  version?: string | null;
  /** Authoritative, host-allowlisted https documentation URL, or null when unavailable. */
  url?: string | null;
  /** Optional URL fragment/anchor for a specific capability or reason. */
  anchor?: string | null;
  /** True when no authoritative link applies; render the note, never invent a URL. */
  documentation_unavailable: boolean;
  /** Short reviewed note about the documentation, when present. */
  note?: string | null;
}

/** A reviewed, reason-specific explanation template (mirrors Python `ReasonExplanation`). */
export interface ReasonExplanation {
  /** The cause category this explanation is for. */
  reason: ProjectionReasonCode;
  /** Short human label for the category (e.g. `"Destination limit"`). */
  category_label: string;
  /** Reviewed one-line explanation, optionally with a single `{construct}` slot. */
  summary_template: string;
  /** Short, safe remediation guidance for this category. */
  remediation: string;
  /** True only for a genuine destination-specification limit — the one category a link fits. */
  destination_documentation_applies: boolean;
}

/** The versioned capability + documentation entry for one destination (mirrors Python `DestinationCapability`). */
export interface DestinationCapability {
  /** Stable emitter target key (e.g. `"openapi"`). */
  key: string;
  /** Output format key the emitter produces (e.g. `"openapi-3.1"`). */
  format: string;
  /** Human label for the destination. */
  label: string;
  /** Whether this destination is available / experimental / unavailable. */
  availability: DestinationAvailability;
  /** Reviewed destination-documentation metadata, with a safe fallback. */
  documentation: DocumentationEvidence;
  /** The emitter implementation version this entry describes. */
  emitter_version: string;
  /** The registry contract version this entry belongs to. */
  registry_version: string;
  /** When this entry's link/explanation was last reviewed. */
  review_date: string;
}

/** The full registry view exposed to the UI (mirrors Python `CapabilityRegistrySnapshot`). */
export interface CapabilityRegistrySnapshot {
  /** The registry contract version. */
  version: string;
  /** When the registry links/explanations were last reviewed. */
  review_date: string;
  /** The canonical set of valid reason-code strings, sorted. */
  reason_codes: string[];
  /** The reviewed explanation for each reason code, in taxonomy order. */
  reasons: ReasonExplanation[];
  /** One capability entry per registered destination, in key order. */
  destinations: DestinationCapability[];
}

/** Return true when `code` is a member of the canonical reason taxonomy. */
export function isKnownReasonCode(code: string): code is ProjectionReasonCode {
  return REASON_CODE_SET.has(code);
}

/**
 * Assert `code` is a known reason code, else throw.
 *
 * @throws Error when `code` is not a member of {@link REASON_CODES}.
 */
export function assertKnownReasonCode(code: string): ProjectionReasonCode {
  if (!isKnownReasonCode(code)) {
    throw new Error(`unknown projection reason code: ${JSON.stringify(code)}`);
  }
  return code;
}

/**
 * Return true when `url` is a safe documentation link: an absolute `https` URL whose host is
 * an exact, lowercased member of {@link ALLOWED_DOCUMENTATION_HOSTS}, with no embedded
 * credentials and no explicit port. Mirrors Python `validate_documentation_url`.
 */
export function isSafeDocumentationUrl(url: string | null | undefined): boolean {
  if (typeof url !== 'string' || url.length === 0) {
    return false;
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'https:') {
    return false;
  }
  if (parsed.username || parsed.password) {
    return false;
  }
  if (parsed.port !== '') {
    return false;
  }
  return ALLOWED_DOCUMENTATION_HOSTS.has(parsed.hostname.toLowerCase());
}

/**
 * Assert `url` is a safe documentation link, else throw.
 *
 * @throws Error when `url` fails {@link isSafeDocumentationUrl}.
 */
export function assertSafeDocumentationUrl(url: string): string {
  if (!isSafeDocumentationUrl(url)) {
    throw new Error(`unsafe documentation URL: ${JSON.stringify(url)}`);
  }
  return url;
}

/**
 * Return documentation evidence safe to render: if its `url` is present but not safe, strip it
 * to the truthful `documentation_unavailable` fallback rather than surfacing an unsafe link.
 * Evidence with no URL, or a URL that passes the allowlist, is returned unchanged.
 */
export function sanitizeDocumentationEvidence(evidence: DocumentationEvidence): DocumentationEvidence {
  if (evidence.url == null) {
    return evidence;
  }
  if (isSafeDocumentationUrl(evidence.url)) {
    return evidence;
  }
  return {
    ...evidence,
    url: null,
    anchor: null,
    documentation_unavailable: true,
    note:
      evidence.note ??
      'The registered documentation link failed the host allowlist and was withheld.',
  };
}

/** A single problem found while validating a {@link CapabilityRegistrySnapshot}. */
export interface RegistryContractIssue {
  /** Where the issue was found (e.g. `"reasons[2].reason"` or `"destinations.openapi.documentation.url"`). */
  path: string;
  /** Human description of the contract violation. */
  message: string;
}

/**
 * Validate a whole registry snapshot against the UI contract: every reason code (both the
 * declared `reason_codes` set and each `reasons[].reason`) must be a member of the canonical
 * taxonomy, and every destination's documentation `url` — when present — must pass the host
 * allowlist. Returns every issue found (empty array when the snapshot is clean), so a test can
 * assert the live registry is trustworthy and a component can refuse to render an untrusted one.
 */
export function validateRegistrySnapshot(snapshot: CapabilityRegistrySnapshot): RegistryContractIssue[] {
  const issues: RegistryContractIssue[] = [];

  snapshot.reason_codes.forEach((code, index) => {
    if (!isKnownReasonCode(code)) {
      issues.push({ path: `reason_codes[${index}]`, message: `unknown reason code ${JSON.stringify(code)}` });
    }
  });

  snapshot.reasons.forEach((explanation, index) => {
    if (!isKnownReasonCode(explanation.reason)) {
      issues.push({
        path: `reasons[${index}].reason`,
        message: `unknown reason code ${JSON.stringify(explanation.reason)}`,
      });
    }
  });

  snapshot.destinations.forEach((destination) => {
    const url = destination.documentation.url;
    if (url != null && !isSafeDocumentationUrl(url)) {
      issues.push({
        path: `destinations.${destination.key}.documentation.url`,
        message: `unsafe documentation URL ${JSON.stringify(url)}`,
      });
    }
  });

  return issues;
}

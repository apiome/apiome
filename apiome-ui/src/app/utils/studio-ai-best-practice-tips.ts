/**
 * Context-aware Studio AI best-practice tips (#615, #616, #617, #618).
 *
 * Combines the project metadata `domainCategory` (see project-domain-categories)
 * with light heuristics on class and property names so e-commerce, multi-tenant,
 * auth-heavy, secret-bearing, and performance-sensitive workspaces get targeted
 * guidance without calling a model. Each known domain emits several
 * industry-specific modeling patterns (not a single generic hint), plus
 * security-hardening and performance hints when signals match.
 */

import {
  PROJECT_DOMAIN_CATEGORY_NONE,
  getProjectDomainCategory,
  getProjectDomainCategoryLabel,
} from '@/app/utils/project-domain-categories';

export type StudioAiTipSignalContext = {
  domainCategory?: string | null;
  classNames: readonly string[];
  /** Reusable property definition names — secret / credential (#617) and performance (#618) heuristics. */
  propertyNames?: readonly string[];
};

/** Several actionable patterns per industry; order is stable for tests and UX. */
const DOMAIN_INDUSTRY_PATTERNS_BY_ID: Readonly<Record<string, readonly string[]>> = {
  ecommerce: [
    'Model inventory tracking with explicit stock levels, reservations, or holds so concurrent checkouts cannot oversell.',
    'Attach tax jurisdiction and breakdown to orders and refunds, not only to catalog SKUs.',
    'Require idempotency keys on checkout and capture mutations so network retries cannot double-charge.',
  ],
  saas: [
    'Add tenant isolation fields: carry tenant or workspace identifiers on every tenant-owned entity and enforce them at the API boundary.',
    'Model subscription lifecycle (trial, active, past_due, canceled) as explicit states with valid transitions.',
    'Persist metered usage counters or event streams separately from billing invoices for reconciliation.',
  ],
  iot: [
    'Model stable device identity, firmware revision, and last-seen timestamps alongside telemetry payloads.',
    'Version device configuration separately from telemetry readings so rollbacks do not erase history.',
    'Prefer UTC timestamps and optional quality flags on sensor samples for downstream aggregation.',
  ],
  social: [
    'Separate public profile fields from private account data; model follow and block relationships explicitly.',
    'Store moderation decisions and appeal state on content entities for audit and safety workflows.',
    'Model notification preferences per channel so email, push, and in-app opt-outs stay independent.',
  ],
  gaming: [
    'Persist authoritative server timestamps for match outcomes and anti-cheat audit fields.',
    'Isolate player economy balances from cosmetic inventory to limit exploit blast radius.',
    'Record session and match identifiers on progression events for replay and dispute handling.',
  ],
  travel: [
    'Capture cancellations, no-shows, and rebooking lineage on reservations.',
    'Use locale-aware currency and explicit exchange-rate snapshots on cross-border charges.',
    'Model guest counts, room types, and special requests as first-class fields on booking objects.',
  ],
  media: [
    'Track rights windows, territory, and entitlement identifiers on catalog entities.',
    'Distinguish editorial metadata from distribution manifests so syndication cannot drift silently.',
    'Model series or season grouping explicitly when episodes share contracts or blackout rules.',
  ],
  healthcare: [
    'Prefer coded values (code system + code + display) where interoperability or regulation expects them.',
    'Scope clinical narrative and PHI-bearing fields to access-controlled surfaces and provenance metadata.',
    'Reference patients, practitioners, and organizations with stable identifiers suitable for FHIR-style linking.',
  ],
  finance: [
    'Model money movement as append-only ledger entries; correct mistakes with reversing entries, not in-place edits.',
    'Require idempotency keys on payment instructions and payouts.',
    'Separate authorized, captured, and settled amounts on card or ACH flows.',
  ],
  education: [
    'Version course content separately from enrollments so curriculum updates do not rewrite student history.',
    'Record graded artifacts with grader identity and timestamp when outcomes must be auditable.',
    'Model cohort or section membership apart from the user account for roster and permission boundaries.',
  ],
  realestate: [
    'Model offer contingencies and earnest-money deadlines explicitly on transaction objects.',
    'Track listing status transitions (active, pending, closed) with effective dates for MLS-style workflows.',
    'Represent agency relationships and dual-agency disclosure flags where brokerage rules apply.',
  ],
  logistics: [
    'Track shipment status transitions with actor and timestamp metadata for exception handling and SLA evidence.',
    'Model stops or legs explicitly when one consignment spans multiple carriers or hubs.',
    'Capture proof-of-delivery signatures or scan events as immutable milestone records.',
  ],
};

function industryPatternsForDomain(domainId: string): readonly string[] {
  const explicit = DOMAIN_INDUSTRY_PATTERNS_BY_ID[domainId];
  if (explicit?.length) return explicit;
  const cat = getProjectDomainCategory(domainId);
  return cat ? [cat.hint] : [];
}

/**
 * Split a CamelCase or snake_case class name into its constituent words so that
 * word-boundary anchors work on compound names.
 *
 * Examples:
 *   OAuthSession      → "OAuthSession O Auth Session"
 *   OrganizationMember → "OrganizationMember Organization Member"
 *   refresh_token      → "refresh_token refresh token"
 */
function tokenizeClassName(name: string): string {
  return name
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')    // fooBar → foo Bar
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2') // XMLParser → XML Parser
    .replace(/_/g, ' ');
}

const AUTH_CLASS_SIGNAL =
  /\b(Session|Sessions|Token|Tokens|OAuth|Refresh|JWT|Jwt|Mfa|Credential|Credentials|Identity|Login|Auth|Password|Otp|Oidc|Saml)\b/i;

const TENANT_CLASS_SIGNAL = /\b(Tenant|Tenants|Organization|Organizations|Workspace|Workspaces|OrgMembership)\b/i;

/** Password-like fields on classes or reusable properties (includes camel/snake compounds). */
const PASSWORD_FIELD_SIGNAL =
  /\b(password|passwd|pwd)\b|password[_-]?hash|passwd[_-]?hash|\bpassword\s+hash\b/i;

/** Config-secret style names that should suggest vault / secret-manager handling. */
const CONFIG_SECRET_FIELD_SIGNAL =
  /\b(secret|secrets|apikey|api[_-]?key|api\s+key|privatekey|private[_-]?key|private\s+key|clientsecret|client[_-]?secret|client\s+secret|signingkey|signing[_-]?key|signing\s+key|accesstoken|access[_-]?token|access\s+token|refreshtoken|refresh[_-]?token|refresh\s+token|bearertoken|bearer[_-]?token|bearer\s+token|webhooksecret|webhook[_-]?secret|webhook\s+secret)\b/i;

/** Sensitive identifiers that should be redacted from logs/exports but not loaded from a vault. */
const SENSITIVE_DATA_FIELD_SIGNAL =
  /\b(cvv|cvc|\bpan\b|ssn|social[_-]?security|social\s+security)\b/i;

const SENSITIVE_CLASS_NAME_SIGNAL =
  /\b(ApiKey|ApiSecret|ClientSecret|PrivateKey|SigningKey|WebhookSecret|HmacSecret)\b/;

/** Compound names like `StripeWebhookEndpoint` must match without assuming token boundaries. */
const WEBHOOK_CLASS_SIGNAL = /Webhook/i;

/** Response caches, edge caches, and explicit revalidation hooks. */
const CACHE_LAYER_SIGNAL =
  /\b(Cache|Caching|Cached|Redis|Memcached|CDN)\b|ETag|\bE\s+Tag\b/i;

/** Background workers, queues, and outbox-style durability. */
const QUEUE_WORKER_SIGNAL =
  /\b(Queue|Job|Worker|Outbox)\b|BackgroundTask|AsyncJob|DeadLetter|\bBackground\s+Task\b|\bAsync\s+Job\b|\bDead\s+Letter\b/i;

/** List endpoints and stable paging primitives (includes tokenized `page_token` → "page token"). */
const PAGINATION_SIGNAL =
  /\b(Pagination|PageToken|CursorToken|Keyset|InfiniteScroll|OffsetPage)\b|\bpage\s+token\b|\bcursor\s+token\b/i;

/** Search indexes and autocomplete projections (`SearchIndex` often appears inside CamelCase names). */
const SEARCH_INDEX_SIGNAL =
  /SearchIndex|Elasticsearch|OpenSearch|FullText|AutocompleteIndex|\bsearch\s+index\b/i;

/** Large imports, exports, or migrations (`CsvExport` often appears inside CamelCase names). */
const BULK_IO_SIGNAL =
  /BulkImport|BulkExport|CsvExport|ExportJob|ImportBatch|DataMigration|\bcsv\s+export\b|\bexport\s+job\b/i;

/** Large binary or media payloads. */
const MEDIA_PAYLOAD_SIGNAL =
  /\b(Attachment|Blob)\b|MediaAsset|VideoAsset|ImageUpload|FileUpload|BinaryPayload|\bMedia\s+Asset\b|\bVideo\s+Asset\b|\bImage\s+Upload\b|\bFile\s+Upload\b|\bBinary\s+Payload\b/i;

/** Hot read paths such as feeds and timelines (`Timeline` often appears inside CamelCase names). */
const FEED_TIMELINE_SIGNAL =
  /Timeline|ActivityStream|NotificationFeed|Fanout|\bfeed\b/i;

function asBullet(line: string): string {
  const t = line.trim();
  if (t.startsWith('-')) return t;
  return `- ${t}`;
}

function dedupeBullets(lines: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of lines) {
    const line = asBullet(raw);
    const key = line.slice(1).trim().toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(line);
  }
  return out;
}

function collectSecurityHardeningTipLines(signals: StudioAiTipSignalContext): string[] {
  const rawDomain = signals.domainCategory?.trim() || '';
  const domainId = rawDomain === PROJECT_DOMAIN_CATEGORY_NONE ? '' : rawDomain;
  const classNames = signals.classNames.filter(Boolean);
  const propertyNames = signals.propertyNames?.filter(Boolean) ?? [];

  const classHaystack = classNames.map((c) => `${c} ${tokenizeClassName(c)}`).join(' ');
  const propHaystack = propertyNames.map((p) => `${p} ${tokenizeClassName(p)}`).join(' ');
  const combinedHaystack = `${classHaystack} ${propHaystack}`.trim();

  const lines: string[] = [];

  const configSecretLikePropsOrClasses =
    CONFIG_SECRET_FIELD_SIGNAL.test(propHaystack) ||
    CONFIG_SECRET_FIELD_SIGNAL.test(classHaystack) ||
    SENSITIVE_CLASS_NAME_SIGNAL.test(classHaystack);
  const sensitiveDataLikePropsOrClasses =
    SENSITIVE_DATA_FIELD_SIGNAL.test(propHaystack) ||
    SENSITIVE_DATA_FIELD_SIGNAL.test(classHaystack);

  if (PASSWORD_FIELD_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Never persist cleartext passwords; store salted password hashes with explicit algorithm and work-factor metadata.',
      ),
    );
  }

  if (AUTH_CLASS_SIGNAL.test(classHaystack)) {
    lines.push(
      asBullet(
        'Enforce rate limits and credential-stuffing protections on authentication and token issuance endpoints.',
      ),
    );
  }

  if (configSecretLikePropsOrClasses) {
    lines.push(
      asBullet(
        'Load secrets from a vault or secret manager in production; avoid embedding real values in schemas, examples, or defaults.',
      ),
    );
  }

  if (configSecretLikePropsOrClasses || sensitiveDataLikePropsOrClasses) {
    lines.push(
      asBullet(
        'Exclude secret-bearing fields from structured logs, error payloads, and analytics exports.',
      ),
    );
  }

  if (domainId === 'finance' || domainId === 'ecommerce') {
    lines.push(
      asBullet(
        'Avoid storing full card numbers or CVV; reference processor tokens and non-sensitive display fields instead.',
      ),
    );
  }

  if (domainId === 'healthcare') {
    lines.push(
      asBullet(
        'Encrypt PHI at rest and in transit; narrow raw-field access to services that truly require it.',
      ),
    );
  }

  if (WEBHOOK_CLASS_SIGNAL.test(classHaystack)) {
    lines.push(
      asBullet(
        'Verify webhook signatures (and timestamps when replay resistance matters) before trusting inbound payloads.',
      ),
    );
  }

  return lines;
}

function collectPerformanceOptimizationTipLines(signals: StudioAiTipSignalContext): string[] {
  const classNames = signals.classNames.filter(Boolean);
  const propertyNames = signals.propertyNames?.filter(Boolean) ?? [];

  const classHaystack = classNames.map((c) => `${c} ${tokenizeClassName(c)}`).join(' ');
  const propHaystack = propertyNames.map((p) => `${p} ${tokenizeClassName(p)}`).join(' ');
  const combinedHaystack = `${classHaystack} ${propHaystack}`.trim();

  const lines: string[] = [];

  if (CACHE_LAYER_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Namespace cache entries per tenant or bounded context; record TTL or stale-after semantics so callers know when refreshed reads are required.',
      ),
    );
  }

  if (QUEUE_WORKER_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Make background jobs idempotent with dedupe keys where retries are possible; model retry counts and terminal failure states for safe backoff under load.',
      ),
    );
  }

  if (PAGINATION_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Prefer opaque cursors or keyset pagination fields on large lists over unbounded offset scans as data grows.',
      ),
    );
  }

  if (SEARCH_INDEX_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Treat search documents as projections of canonical entities; model index lag or sequence tokens when read-after-write consistency matters.',
      ),
    );
  }

  if (BULK_IO_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Stream or chunk large imports and exports; avoid schemas that require loading unbounded collections into one aggregate.',
      ),
    );
  }

  if (MEDIA_PAYLOAD_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Keep heavy binary metadata separate from core transactional rows; reference storage keys, checksums, and content types instead of inlining large payloads.',
      ),
    );
  }

  if (FEED_TIMELINE_SIGNAL.test(combinedHaystack)) {
    lines.push(
      asBullet(
        'Model fan-out or materialized timelines explicitly; denormalize read models when hot paths must stay predictable at scale.',
      ),
    );
  }

  return lines;
}

export function collectStudioAiBestPracticeTipLines(signals: StudioAiTipSignalContext): string[] {
  const rawDomain = signals.domainCategory?.trim() || '';
  const domainId = rawDomain === PROJECT_DOMAIN_CATEGORY_NONE ? '' : rawDomain;
  const classNames = signals.classNames.filter(Boolean);
  const haystack = classNames
    .map((c) => `${c} ${tokenizeClassName(c)}`)
    .join(' ');

  const lines: string[] = [];

  if (domainId) {
    for (const pattern of industryPatternsForDomain(domainId)) {
      lines.push(asBullet(pattern));
    }
  }

  if (AUTH_CLASS_SIGNAL.test(haystack)) {
    lines.push(asBullet('Implement refresh token pattern'));
  }

  if (domainId !== 'saas' && TENANT_CLASS_SIGNAL.test(haystack)) {
    lines.push(asBullet('Add tenant isolation fields'));
  }

  for (const line of collectSecurityHardeningTipLines(signals)) {
    lines.push(line);
  }

  for (const line of collectPerformanceOptimizationTipLines(signals)) {
    lines.push(line);
  }

  return dedupeBullets(lines);
}

export function collectStudioAiBestPracticeLinesFromStudio(ctx: {
  project?: { domainCategory?: string | null } | null;
  classes: Array<{ name: string }>;
  properties?: Array<{ name: string }>;
} | null | undefined): string[] {
  if (!ctx) return [];
  return collectStudioAiBestPracticeTipLines({
    domainCategory: ctx.project?.domainCategory,
    classNames: ctx.classes.map((c) => c.name),
    propertyNames: ctx.properties?.map((p) => p.name) ?? [],
  });
}

/** Human label for UI / preamble headings; null when unknown or unset. */
export function studioAiBestPracticeDomainHeadingFromStudio(
  project: { domainCategory?: string | null } | null | undefined,
): string | null {
  const id = project?.domainCategory?.trim();
  if (!id || id === PROJECT_DOMAIN_CATEGORY_NONE) return null;
  return getProjectDomainCategoryLabel(id) ?? id;
}

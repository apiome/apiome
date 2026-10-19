/**
 * The schema registry in the UI — CDG-4.5 (#5977).
 *
 * Pure rules shared by the `/api/schema-registry/*` proxy, the catalog item's **Subjects** tab, the
 * Workspace **Schema registry** page and the Catalog **Registry** chip: the wire shapes of the
 * CDG-4.2 routes (`/v1/tenants/{slug}/schema-registry`), which catalog formats a subject can hold,
 * which proxy paths are allowed, and the serializer configuration snippets.
 */

import { resolveCatalogFormat } from '@/app/utils/catalog-format-registry';

/** Compatibility levels a tenant or subject can be set to (Confluent's seven). */
export const COMPATIBILITY_LEVELS = [
  'NONE',
  'BACKWARD',
  'BACKWARD_TRANSITIVE',
  'FORWARD',
  'FORWARD_TRANSITIVE',
  'FULL',
  'FULL_TRANSITIVE',
] as const;

export type CompatibilityLevel = (typeof COMPATIBILITY_LEVELS)[number];

/** Registry modes; `READONLY` refuses every new version. */
export const REGISTRY_MODES = ['READWRITE', 'READONLY'] as const;

export type RegistryMode = (typeof REGISTRY_MODES)[number];

/** Subject naming strategies, as stored. */
export const SUBJECT_STRATEGIES = ['topic', 'record', 'topic_record'] as const;

export type SubjectStrategy = (typeof SUBJECT_STRATEGIES)[number];

/** What each strategy names a subject, for the attach form's options. */
export const STRATEGY_LABELS: Readonly<Record<SubjectStrategy, string>> = {
  topic: 'Topic — orders-value',
  record: 'Record — acme.Order-value',
  topic_record: 'Topic + record — orders-acme.Order-value',
};

/** The tenant's registry defaults (`GET /config`), plus what the proxy adds for the snippets. */
export interface RegistryConfig {
  compatibilityLevel: CompatibilityLevel;
  mode: RegistryMode;
  /** The tenant slug (added by the proxy). */
  tenantSlug?: string;
  /** The Confluent-compatible base URL serializers point at (added by the proxy). */
  registryUrl?: string;
}

/** A schema subject (`SubjectOut`). */
export interface SchemaSubject {
  name: string;
  strategy: SubjectStrategy | null;
  /** `null` = the tenant default. */
  compatibilityLevel: CompatibilityLevel | null;
  effectiveCompatibilityLevel: CompatibilityLevel;
  mode: RegistryMode;
  /** The catalog item new versions are registered into. */
  projectId: string | null;
  versionCount: number;
  latestVersion: number | null;
  createdAt: string;
  updatedAt: string;
}

/** One version of a subject (`SubjectVersionOut`). */
export interface SubjectVersion {
  subject: string;
  version: number;
  /** The schema id, shared by every subject holding the same schema. */
  id: number;
  schemaType: 'AVRO' | 'JSON' | 'PROTOBUF';
  fingerprint: string;
  projectId: string;
  versionRecordId: string;
  createdAt: string;
}

/** Catalog format ids (see `catalog-format-registry`) a subject can hold. */
const REGISTRY_FORMAT_IDS: ReadonlySet<string> = new Set(['avro', 'jsonschema', 'protobuf']);

/**
 * Whether a catalog item of this format can back a schema subject (Avro, JSON Schema, Protobuf).
 *
 * @param sourceFormat - The item's `sourceFormat`.
 * @returns True for the three schema formats.
 */
export function isRegistryFormat(sourceFormat: string | null | undefined): boolean {
  const format = resolveCatalogFormat(sourceFormat);
  return format !== undefined && REGISTRY_FORMAT_IDS.has(format.id);
}

/**
 * The subjects backed by one catalog item, by name.
 *
 * @param subjects - Every live subject of the tenant.
 * @param itemId - The catalog item id.
 * @returns The item's subjects.
 */
export function subjectsForItem(subjects: readonly SchemaSubject[], itemId: string): SchemaSubject[] {
  return subjects.filter((subject) => subject.projectId === itemId).sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Catalog item id → the names of the subjects it backs, for the Catalog **Registry** chip.
 *
 * @param subjects - Every live subject of the tenant.
 * @returns A map with one entry per item that backs at least one subject.
 */
export function subjectNamesByItem(subjects: readonly SchemaSubject[]): Map<string, string[]> {
  const byItem = new Map<string, string[]>();
  for (const subject of subjects) {
    if (!subject.projectId) continue;
    const names = byItem.get(subject.projectId) ?? [];
    names.push(subject.name);
    byItem.set(subject.projectId, names);
  }
  for (const names of byItem.values()) names.sort((a, b) => a.localeCompare(b));
  return byItem;
}

/**
 * A subject's level as a reader sees it: its own, or the tenant default marked as such.
 *
 * @param subject - The subject.
 * @returns e.g. `NONE` or `BACKWARD (workspace default)`.
 */
export function subjectLevelLabel(subject: SchemaSubject): string {
  return subject.compatibilityLevel ?? `${subject.effectiveCompatibilityLevel} (workspace default)`;
}

/** Longest subject name REST accepts. */
export const SUBJECT_NAME_MAX = 255;

/**
 * Why a subject name typed into the attach form cannot be used, or `null` when it can.
 *
 * @param name - The name as typed.
 * @returns The problem, or `null`.
 */
export function subjectNameProblem(name: string): string | null {
  if (!name.trim()) return 'Enter a subject name, for example orders-value.';
  if (name.length > SUBJECT_NAME_MAX) return `A subject name is at most ${SUBJECT_NAME_MAX} characters.`;
  if (/[\u0000-\u001f\u007f]/.test(name)) return 'A subject name cannot contain control characters.';
  return null;
}

/**
 * The Confluent-compatible base URL of a tenant (CDG-4.3): the REST host plus `/registry/schema/{slug}`.
 *
 * @param restApiBaseUrl - The REST base URL, ending in `/v1`.
 * @param tenantSlug - The tenant slug.
 * @returns e.g. `https://api.example.com/registry/schema/acme`.
 */
export function registryBaseUrl(restApiBaseUrl: string, tenantSlug: string): string {
  const host = restApiBaseUrl.replace(/\/+$/, '').replace(/\/v1$/, '');
  return `${host}/registry/schema/${encodeURIComponent(tenantSlug)}`;
}

/** A serializer configuration snippet. */
export interface SerializerSnippet {
  id: 'python' | 'java' | 'spring';
  label: string;
  /** The library or file the snippet is for. */
  caption: string;
  code: string;
}

/** The placeholder the snippets put where the API key goes; a key is never printed. */
export const API_KEY_PLACEHOLDER = '<api-key>';

/**
 * Copy-paste serializer configuration for `confluent-kafka`, `kafka-avro-serializer` and Spring Kafka.
 *
 * @param registryUrl - The tenant's Confluent-compatible base URL.
 * @returns One snippet per client, Python first.
 */
export function serializerSnippets(registryUrl: string): SerializerSnippet[] {
  return [
    {
      id: 'python',
      label: 'Python',
      caption: 'confluent-kafka',
      code: [
        'from confluent_kafka.schema_registry import SchemaRegistryClient',
        '',
        'registry = SchemaRegistryClient({',
        `    "url": "${registryUrl}",`,
        `    "basic.auth.user.info": "producer:${API_KEY_PLACEHOLDER}",`,
        '})',
      ].join('\n'),
    },
    {
      id: 'java',
      label: 'Java',
      caption: 'kafka-avro-serializer (.properties)',
      code: [
        `schema.registry.url=${registryUrl}`,
        'basic.auth.credentials.source=USER_INFO',
        `basic.auth.user.info=producer:${API_KEY_PLACEHOLDER}`,
      ].join('\n'),
    },
    {
      id: 'spring',
      label: 'Spring',
      caption: 'Spring Kafka (application.yml)',
      code: [
        'spring:',
        '  kafka:',
        '    properties:',
        `      schema.registry.url: ${registryUrl}`,
        '      basic.auth.credentials.source: USER_INFO',
        `      basic.auth.user.info: producer:${API_KEY_PLACEHOLDER}`,
      ].join('\n'),
    },
  ];
}

/** HTTP methods the proxy forwards. */
export type RegistryProxyMethod = 'GET' | 'PUT' | 'POST' | 'DELETE';

/**
 * The REST path (below `/v1/tenants/{slug}/schema-registry`) a proxy request may reach, or `null`.
 *
 * Only these shapes are forwarded, so a crafted path can never address another REST route:
 *
 * | Path | Methods |
 * | --- | --- |
 * | `config` | GET, PUT |
 * | `subjects` | GET |
 * | `subjects/{s}` | GET, PUT, DELETE |
 * | `subjects/{s}/versions` | GET |
 * | `subjects/{s}/versions/{n or latest}` | GET |
 * | `subjects/{s}/attach` | POST |
 *
 * Registering a schema stays with the CLI and the APIs; the UI attaches existing catalog items.
 *
 * @param segments - The decoded path segments after `/api/schema-registry/`.
 * @param method - The request method.
 * @returns The encoded REST path, or `null` when the request is not allowed.
 */
export function registryProxyPath(segments: readonly string[], method: RegistryProxyMethod): string | null {
  const [head, subject, tail, version, ...rest] = segments;
  if (rest.length > 0) return null;
  if (head === 'config' && segments.length === 1) return method === 'GET' || method === 'PUT' ? 'config' : null;
  if (head !== 'subjects') return null;
  if (segments.length === 1) return method === 'GET' ? 'subjects' : null;
  if (subjectNameProblem(subject) !== null) return null;
  const base = `subjects/${encodeURIComponent(subject)}`;
  if (segments.length === 2) return method === 'POST' ? null : base;
  if (tail === 'attach' && segments.length === 3) return method === 'POST' ? `${base}/attach` : null;
  if (tail !== 'versions' || method !== 'GET') return null;
  if (segments.length === 3) return `${base}/versions`;
  return version === 'latest' || /^[1-9][0-9]{0,8}$/.test(version) ? `${base}/versions/${version}` : null;
}

/**
 * The fields a proxy forwards for a write, so the browser cannot send REST anything else.
 *
 * @param path - The allowed REST path (from {@link registryProxyPath}).
 * @param raw - The parsed request body.
 * @returns The body to forward.
 */
export function registryProxyBody(path: string, raw: unknown): Record<string, unknown> {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const fields =
    path === 'config' ? ['compatibilityLevel', 'mode']
    : path.endsWith('/attach') ? ['projectId', 'strategy']
    : ['strategy', 'compatibilityLevel', 'mode'];
  const body: Record<string, unknown> = {};
  for (const field of fields) {
    const value = source[field];
    if (typeof value === 'string' && value.length <= 255) body[field] = value;
  }
  return body;
}

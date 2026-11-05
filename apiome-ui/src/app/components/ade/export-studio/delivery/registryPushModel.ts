/**
 * The Review step's **Registry** destination — the pure half (MFX-46.3, #4381).
 *
 * An Avro, JSON Schema or Protobuf export can be registered on a schema registry through one of the
 * workspace's `schema-registry` connectors (`POST /v1/export/{tenant}/schema-registry/push`, MFX-19.4).
 * The connector holds the registry URL and credentials; the browser only names it. This module holds what
 * the panel computes without React: which targets can be pushed, the request body (validated), and the
 * words of each subject's status.
 */

/** A registry push format (mirror of REST `RegistryFormat`). */
export type RegistryFormat = 'avro' | 'json-schema' | 'protobuf';

/** How subjects are named (mirror of REST `SubjectNaming`). */
export type SubjectNaming = 'record_name' | 'topic_name' | 'topic_record_name';

/** Export target keys (or formats) that a schema registry can hold, and the push format of each. */
const REGISTRY_FORMATS: Readonly<Record<string, RegistryFormat>> = {
  avro: 'avro',
  'json-schema': 'json-schema',
  protobuf: 'protobuf',
  proto3: 'protobuf',
};

/**
 * The push format of an export target, or null when a schema registry cannot hold it.
 *
 * @param targetKey The target's registry key (e.g. `protobuf`).
 * @param format The target's format (e.g. `proto3`), tried when the key is not one.
 * @returns The format to push, or null.
 */
export function registryFormatFor(targetKey: string | null | undefined, format?: string | null): RegistryFormat | null {
  return REGISTRY_FORMATS[targetKey ?? ''] ?? REGISTRY_FORMATS[format ?? ''] ?? null;
}

/** A `schema-registry` connector, as the panel lists it. */
export interface RegistryConnector {
  id: string;
  name: string;
  baseUrl?: string | null;
}

/** The form's state. */
export interface RegistryPushDraft {
  connectorId: string;
  subjectNaming: SubjectNaming;
  topic: string;
  subjectRole: 'value' | 'key';
  dryRun: boolean;
}

/** The form's starting state: record-name subjects, values, a real push. */
export const EMPTY_REGISTRY_DRAFT: RegistryPushDraft = {
  connectorId: '',
  subjectNaming: 'record_name',
  topic: '',
  subjectRole: 'value',
  dryRun: false,
};

/** The subject naming strategies, in words. */
export const SUBJECT_NAMING_LABELS: Readonly<Record<SubjectNaming, string>> = {
  record_name: 'Record name ({record}-value)',
  topic_name: 'Topic name ({topic}-value)',
  topic_record_name: 'Topic and record ({topic}-{record}-value)',
};

/** What the export being pushed is. */
export interface RegistryPushSource {
  format: RegistryFormat;
  artifact: string;
  version: string | null;
  options: Record<string, unknown> | null;
}

/**
 * Why the draft cannot be pushed yet, or null when it can.
 *
 * @param draft The form's state.
 * @returns The problem, in words, or null.
 */
export function registryDraftProblem(draft: RegistryPushDraft): string | null {
  if (!draft.connectorId) return 'Choose a schema registry connector.';
  if (draft.subjectNaming !== 'record_name' && !draft.topic.trim()) return 'Enter the Kafka topic the subjects are named after.';
  return null;
}

/**
 * The `POST …/schema-registry/push` body.
 *
 * @param source The export.
 * @param draft The form's state (assumed valid: see {@link registryDraftProblem}).
 * @returns The body.
 */
export function registryPushBody(source: RegistryPushSource, draft: RegistryPushDraft): Record<string, unknown> {
  const body: Record<string, unknown> = {
    format: source.format,
    artifact: source.artifact,
    version: source.version,
    connector_id: draft.connectorId,
    subject_naming: draft.subjectNaming,
    subject_role: draft.subjectRole,
    dry_run: draft.dryRun,
  };
  if (source.options && Object.keys(source.options).length > 0) body.options = source.options;
  if (draft.subjectNaming !== 'record_name') body.topic = draft.topic.trim();
  return body;
}

/** One subject's result (mirror of REST `RegistryPushSubjectResult`). */
export interface RegistrySubjectResult {
  subject: string;
  file: string;
  schema_type?: string;
  status: 'registered' | 'already_registered' | 'would_register' | 'incompatible' | 'failed' | 'skipped' | string;
  schema_id?: number | null;
  version?: number | null;
  messages?: string[];
}

/** The push's answer (mirror of REST `RegistryPushResponse`). */
export interface RegistryPushResult {
  registry_url: string;
  dry_run: boolean;
  summary: Record<string, number>;
  subjects: RegistrySubjectResult[];
}

/** A subject status in words, with its tone. */
export function subjectStatus(status: string): { label: string; tone: 'ok' | 'warn' | 'danger' | 'neutral' } {
  switch (status) {
    case 'registered':
      return { label: 'Registered', tone: 'ok' };
    case 'already_registered':
      return { label: 'Already registered', tone: 'ok' };
    case 'would_register':
      return { label: 'Would register', tone: 'neutral' };
    case 'incompatible':
      return { label: 'Incompatible', tone: 'warn' };
    case 'skipped':
      return { label: 'Skipped', tone: 'warn' };
    case 'failed':
      return { label: 'Failed', tone: 'danger' };
    default:
      return { label: status, tone: 'neutral' };
  }
}

/** `version 3 · id 41` — where the subject's schema now lives, or null when it was not registered. */
export function subjectWhere(result: RegistrySubjectResult): string | null {
  const parts: string[] = [];
  if (result.version != null) parts.push(`version ${result.version}`);
  if (result.schema_id != null) parts.push(`id ${result.schema_id}`);
  return parts.length > 0 ? parts.join(' · ') : null;
}

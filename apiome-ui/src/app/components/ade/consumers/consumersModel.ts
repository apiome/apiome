/**
 * The consumer contract registry's rules, in one place — CTG-4.1 (#4479).
 *
 * Every judgement the Consumers screen makes about a row lives here rather than inside a
 * component: what a consumer's contract *status* is, how its surface reads in one line, what
 * an unresolved interaction is called, and what the picker's checkbox state means when it is
 * turned back into a request. The components draw; this module decides.
 *
 * ### Field names are snake_case on purpose
 *
 * The REST models for this feature serialize with their Python field names (no camelCase
 * aliases), so `operation_count` and `schema_pointer` are what actually arrives. Transcribing
 * them here rather than renaming keeps one spelling between the API contract, this model, and
 * the tests — the alternative is a mapping layer whose only job is to be wrong once.
 */

// ---------------------------------------------------------------------------------------
// Wire shapes
// ---------------------------------------------------------------------------------------

/** Where a declared field lives in the exchange. */
export type FieldLocation = 'response' | 'request' | 'parameter';

/** One field a consumer declared it uses. */
export interface ContractField {
  /** Operation-anchored JSON Pointer — the field's identity inside the contract. */
  pointer: string;
  /** Where the node actually lives (a `$ref` target, or the same pointer). */
  schema_pointer: string;
  location: FieldLocation;
  /** Response status code, for a response field. */
  status: string | null;
  /** Media type, for a body field. */
  media_type: string | null;
  /** Dotted data path, or the parameter name. */
  path: string;
}

/** One operation a consumer declared it calls. */
export interface ContractOperation {
  method: string;
  path: string;
  pointer: string;
  operation_id: string | null;
  summary: string | null;
  fields: ContractField[];
}

/** A whole declared surface. */
export interface ContractSurface {
  schema_version: string;
  operations: ContractOperation[];
}

/** Something the importer or the picker could not place. */
export interface UnresolvedInteraction {
  reason: string;
  message: string;
  description: string | null;
  method: string | null;
  path: string | null;
  status: string | null;
  field_path: string | null;
}

/** One stored contract revision. */
export interface ConsumerContract {
  id: string;
  consumer_id: string;
  revision: number;
  is_current: boolean;
  source: 'pact' | 'manual';
  version_id: string | null;
  version_label: string | null;
  surface: ContractSurface;
  operation_count: number;
  field_count: number;
  unresolved: UnresolvedInteraction[];
  unresolved_count: number;
  source_metadata: Record<string, unknown>;
  source_digest: string | null;
  note: string | null;
  actor_label: string | null;
  created_at: string | null;
}

/** A registered consumer. */
export interface Consumer {
  id: string;
  tenant_id: string;
  project_id: string;
  slug: string;
  name: string;
  description: string | null;
  owner: string | null;
  contact: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  deleted_at: string | null;
}

/** A consumer plus its current contract — one row of the list. */
export interface ConsumerSummary {
  consumer: Consumer;
  contract: ConsumerContract | null;
}

/** One field the picker may offer. */
export interface AvailableField {
  pointer: string;
  schema_pointer: string;
  location: FieldLocation;
  path: string;
  status: string | null;
  media_type: string | null;
  type_name: string | null;
  required: boolean;
}

/** One operation the picker may offer. */
export interface AvailableOperation {
  method: string;
  path: string;
  pointer: string;
  operation_id: string | null;
  summary: string | null;
  tags: string[];
  fields: AvailableField[];
  truncated: boolean;
}

/** The picker's catalogue for one stored version. */
export interface AvailableSurface {
  version_record_id: string;
  version_label: string | null;
  operations: AvailableOperation[];
  count: number;
  truncated: boolean;
}

// ---------------------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------------------

/**
 * What a row's contract says about itself.
 *
 * `none` and `partial` are deliberately different states rather than one "needs attention"
 * bucket. A consumer that has declared nothing is a registration nobody has finished; a
 * consumer whose contract carries unresolved interactions is one whose declaration no longer
 * matches the specification — and only the second is evidence about the *API*.
 */
export type ConsumerStatus = 'declared' | 'partial' | 'none';

/** Every status, in the order the toolbar's chips read them. */
export const CONSUMER_STATUSES: readonly ConsumerStatus[] = ['declared', 'partial', 'none'];

/** What each status is called. */
export const CONSUMER_STATUS_LABEL: Readonly<Record<ConsumerStatus, string>> = {
  declared: 'Declared',
  partial: 'Partly resolved',
  none: 'No contract',
};

/** The badge tone each status draws in. */
export const CONSUMER_STATUS_TONE: Readonly<Record<ConsumerStatus, 'ok' | 'warn' | 'neutral'>> = {
  declared: 'ok',
  partial: 'warn',
  none: 'neutral',
};

/**
 * The status of one row.
 *
 * @param summary The row.
 * @returns `none` with no contract, `partial` when the contract carries unresolved entries or
 *   declares no operations at all, otherwise `declared`.
 */
export function consumerStatus(summary: ConsumerSummary): ConsumerStatus {
  const contract = summary.contract;
  if (!contract) return 'none';
  if (contract.unresolved_count > 0 || contract.operation_count === 0) return 'partial';
  return 'declared';
}

// ---------------------------------------------------------------------------------------
// Summaries
// ---------------------------------------------------------------------------------------

/**
 * Pluralize a count with its noun.
 *
 * @param count How many.
 * @param noun The singular noun.
 * @returns `"1 operation"`, `"3 operations"`.
 */
function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

/**
 * A contract's declared surface in one line.
 *
 * @param contract The contract, or `null`.
 * @returns `"Nothing declared yet"`, or `"4 operations · 12 fields"` with the unresolved tally
 *   appended when there is one — a row that hides "3 unresolved" reads as complete coverage.
 */
export function contractSummaryLine(contract: ConsumerContract | null): string {
  if (!contract) return 'Nothing declared yet';
  const parts = [plural(contract.operation_count, 'operation')];
  if (contract.field_count > 0) parts.push(plural(contract.field_count, 'field'));
  if (contract.unresolved_count > 0) {
    parts.push(`${contract.unresolved_count} unresolved`);
  }
  return parts.join(' · ');
}

/**
 * How a contract revision is provenanced, in one line.
 *
 * @param contract The contract, or `null`.
 * @returns `"Revision 3 · imported from Pact · against 1.2.0"`, or an empty string.
 */
export function contractProvenanceLine(contract: ConsumerContract | null): string {
  if (!contract) return '';
  const parts = [`Revision ${contract.revision}`];
  parts.push(contract.source === 'pact' ? 'imported from Pact' : 'declared in the picker');
  if (contract.version_label) parts.push(`against ${contract.version_label}`);
  return parts.join(' · ');
}

/** What each unresolved reason is called, in the reader's words. */
export const UNRESOLVED_REASON_LABEL: Readonly<Record<string, string>> = {
  'operation-not-found': 'Operation not in this version',
  'method-not-declared': 'Method not declared on that path',
  'status-not-declared': 'Response status not declared',
  'media-type-not-declared': 'Media type not declared',
  'field-not-found': 'Field not in the schema',
  'parameter-not-declared': 'Parameter not declared',
  'interaction-not-http': 'Not an HTTP interaction',
  'interaction-malformed': 'Interaction could not be read',
};

/**
 * The label for an unresolved reason.
 *
 * @param reason The stable code.
 * @returns Its label, or the code itself when it is one this build does not know — a new
 *   server-side reason must still be readable rather than rendering as blank.
 */
export function unresolvedReasonLabel(reason: string): string {
  return UNRESOLVED_REASON_LABEL[reason] ?? reason;
}

/**
 * Group unresolved entries by reason, most numerous first.
 *
 * @param entries The entries.
 * @returns One group per reason, each with its label and entries; ties break by reason code so
 *   the same contract always renders in the same order.
 */
export function groupUnresolved(
  entries: readonly UnresolvedInteraction[],
): Array<{ reason: string; label: string; entries: UnresolvedInteraction[] }> {
  const buckets = new Map<string, UnresolvedInteraction[]>();
  for (const entry of entries) {
    const bucket = buckets.get(entry.reason);
    if (bucket) bucket.push(entry);
    else buckets.set(entry.reason, [entry]);
  }
  return [...buckets.entries()]
    .map(([reason, group]) => ({ reason, label: unresolvedReasonLabel(reason), entries: group }))
    .sort((a, b) => b.entries.length - a.entries.length || a.reason.localeCompare(b.reason));
}

// ---------------------------------------------------------------------------------------
// Search, facets, sort
// ---------------------------------------------------------------------------------------

/**
 * Filter rows by a free-text query.
 *
 * Matches the handle, the display name, the owner and the declared paths — the last because
 * "who calls `/invoices`" is the question this screen exists to answer.
 *
 * @param rows The rows.
 * @param query What was typed.
 * @returns The matching rows, in their original order.
 */
export function searchConsumers(
  rows: readonly ConsumerSummary[],
  query: string,
): ConsumerSummary[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...rows];
  return rows.filter((row) => {
    const haystack = [
      row.consumer.slug,
      row.consumer.name,
      row.consumer.owner ?? '',
      row.consumer.description ?? '',
      ...(row.contract?.surface.operations ?? []).map(
        (operation) => `${operation.method} ${operation.path}`,
      ),
    ]
      .join(' ')
      .toLowerCase();
    return haystack.includes(needle);
  });
}

/** The toolbar's view chips. */
export type ConsumerFacet = 'all' | ConsumerStatus;

/** Every facet, in the order the toolbar draws them. */
export const CONSUMER_FACETS: readonly ConsumerFacet[] = ['all', 'declared', 'partial', 'none'];

/** What each chip says. */
export const CONSUMER_FACET_LABELS: Readonly<Record<ConsumerFacet, string>> = {
  all: 'All',
  declared: 'Declared',
  partial: 'Needs attention',
  none: 'No contract',
};

/**
 * Whether a row belongs to a facet.
 *
 * @param row The row.
 * @param facet The chip.
 * @returns True when the chip should count and show it.
 */
export function matchesConsumerFacet(row: ConsumerSummary, facet: ConsumerFacet): boolean {
  return facet === 'all' || consumerStatus(row) === facet;
}

/**
 * How many rows each chip would show.
 *
 * @param rows The rows.
 * @returns A count per facet.
 */
export function consumerFacetCounts(
  rows: readonly ConsumerSummary[],
): Record<ConsumerFacet, number> {
  const counts = { all: rows.length, declared: 0, partial: 0, none: 0 };
  for (const row of rows) counts[consumerStatus(row)] += 1;
  return counts;
}

/** The columns a consumer list can be sorted by. */
export type ConsumerSortColumn = 'consumer' | 'owner' | 'surface' | 'updated';

/**
 * Sort rows by a column.
 *
 * @param rows The rows.
 * @param column Which column.
 * @param direction Ascending or descending.
 * @returns A new sorted array; the input is never mutated.
 */
export function sortConsumers(
  rows: readonly ConsumerSummary[],
  column: ConsumerSortColumn,
  direction: 'asc' | 'desc',
): ConsumerSummary[] {
  const sign = direction === 'asc' ? 1 : -1;
  const value = (row: ConsumerSummary): string | number => {
    switch (column) {
      case 'owner':
        return (row.consumer.owner ?? '').toLowerCase();
      case 'surface':
        return row.contract?.operation_count ?? -1;
      case 'updated':
        return row.contract?.created_at ?? row.consumer.created_at ?? '';
      case 'consumer':
      default:
        return row.consumer.name.toLowerCase() || row.consumer.slug;
    }
  };
  return [...rows].sort((a, b) => {
    const left = value(a);
    const right = value(b);
    if (typeof left === 'number' && typeof right === 'number') return (left - right) * sign;
    return String(left).localeCompare(String(right)) * sign;
  });
}

// ---------------------------------------------------------------------------------------
// The picker
// ---------------------------------------------------------------------------------------

/**
 * The key an operation is tracked by while picking.
 *
 * @param operation Anything carrying a method and a path.
 * @returns `"get /pets"`.
 */
export function operationKey(operation: { method: string; path: string }): string {
  return `${operation.method.toLowerCase()} ${operation.path}`;
}

/**
 * How an operation reads.
 *
 * @param operation Anything carrying a method and a path.
 * @returns `"GET /pets"`.
 */
export function operationLabel(operation: { method: string; path: string }): string {
  return `${operation.method.toUpperCase()} ${operation.path}`;
}

/**
 * The key a field is tracked by while picking.
 *
 * The status is part of the key because the same data path at two statuses is two different
 * declarations — a consumer may read `error.code` on 400 and nothing on 200.
 *
 * @param field Anything carrying a location, a status and a path.
 * @returns A stable key.
 */
export function fieldKey(field: {
  location: string;
  status: string | null;
  path: string;
}): string {
  return `${field.location}|${field.status ?? ''}|${field.path}`;
}

/** Which operations are picked, and which of their fields. */
export type PickerSelection = Readonly<Record<string, readonly string[]>>;

/**
 * Turn a stored contract back into picker state, so editing starts from what is declared.
 *
 * @param contract The current contract, or `null`.
 * @returns The selection; empty when nothing is declared.
 */
export function selectionFromContract(contract: ConsumerContract | null): PickerSelection {
  if (!contract) return {};
  const selection: Record<string, string[]> = {};
  for (const operation of contract.surface.operations) {
    selection[operationKey(operation)] = operation.fields.map(fieldKey);
  }
  return selection;
}

/**
 * Add or remove a whole operation.
 *
 * Unpicking an operation takes its fields with it: a field declared on an operation the
 * consumer does not call is not a statement about anything.
 *
 * @param selection The current selection.
 * @param operation The operation toggled.
 * @returns The new selection.
 */
export function toggleOperation(
  selection: PickerSelection,
  operation: { method: string; path: string },
): PickerSelection {
  const key = operationKey(operation);
  if (key in selection) {
    const next = { ...selection };
    delete next[key];
    return next;
  }
  return { ...selection, [key]: [] };
}

/**
 * Add or remove one field.
 *
 * Picking a field picks its operation too — the two cannot disagree, and making a person click
 * twice to say one thing is the kind of friction that produces wrong contracts.
 *
 * @param selection The current selection.
 * @param operation The operation the field belongs to.
 * @param field The field toggled.
 * @returns The new selection.
 */
export function toggleField(
  selection: PickerSelection,
  operation: { method: string; path: string },
  field: { location: string; status: string | null; path: string },
): PickerSelection {
  const key = operationKey(operation);
  const target = fieldKey(field);
  const current = selection[key] ?? [];
  const next = current.includes(target)
    ? current.filter((entry) => entry !== target)
    : [...current, target];
  return { ...selection, [key]: next };
}

/**
 * Whether an operation is picked.
 *
 * @param selection The current selection.
 * @param operation The operation.
 * @returns True when it is in the selection.
 */
export function isOperationPicked(
  selection: PickerSelection,
  operation: { method: string; path: string },
): boolean {
  return operationKey(operation) in selection;
}

/**
 * Whether a field is picked.
 *
 * @param selection The current selection.
 * @param operation The operation the field belongs to.
 * @param field The field.
 * @returns True when it is in the selection.
 */
export function isFieldPicked(
  selection: PickerSelection,
  operation: { method: string; path: string },
  field: { location: string; status: string | null; path: string },
): boolean {
  return (selection[operationKey(operation)] ?? []).includes(fieldKey(field));
}

/** How many operations and fields a selection holds. */
export interface SelectionTotals {
  operations: number;
  fields: number;
}

/**
 * What a selection amounts to.
 *
 * @param selection The current selection.
 * @returns The two counts, for the dialog's footer sentence.
 */
export function selectionTotals(selection: PickerSelection): SelectionTotals {
  const keys = Object.keys(selection);
  return {
    operations: keys.length,
    fields: keys.reduce((total, key) => total + (selection[key]?.length ?? 0), 0),
  };
}

/** One operation of the request body a picked surface is submitted as. */
export interface SelectionPayloadOperation {
  method: string;
  path: string;
  fields: Array<{ location: string; path: string; status?: string }>;
}

/**
 * Turn picker state into the request body the server resolves.
 *
 * The payload names operations and fields **the way a person picked them** — no pointers. The
 * server resolves each against the stored specification, which is what keeps a stored surface
 * describing something the specification actually contains.
 *
 * @param selection The picked operations and fields.
 * @param catalogue The catalogue the picking was done against, for the method/path spelling.
 * @returns The operations to submit, ordered by path then method so the same picks always
 *   produce the same request.
 */
export function buildSelectionPayload(
  selection: PickerSelection,
  catalogue: readonly AvailableOperation[],
): SelectionPayloadOperation[] {
  const byKey = new Map(catalogue.map((operation) => [operationKey(operation), operation]));
  const payload: SelectionPayloadOperation[] = [];

  for (const key of Object.keys(selection)) {
    const operation = byKey.get(key);
    if (!operation) continue;
    const picked = new Set(selection[key] ?? []);
    payload.push({
      method: operation.method,
      path: operation.path,
      fields: operation.fields
        .filter((field) => picked.has(fieldKey(field)))
        .map((field) => ({
          location: field.location,
          path: field.path,
          ...(field.status ? { status: field.status } : {}),
        })),
    });
  }

  return payload.sort(
    (a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method),
  );
}

/**
 * Group a catalogue's fields by where they live, for the picker's sub-lists.
 *
 * @param operation The catalogue entry.
 * @returns One group per location that has fields, in exchange order (what you send, then what
 *   you get back, then the parameters that select it).
 */
export function groupAvailableFields(
  operation: AvailableOperation,
): Array<{ location: FieldLocation; label: string; fields: AvailableField[] }> {
  const order: ReadonlyArray<{ location: FieldLocation; label: string }> = [
    { location: 'parameter', label: 'Parameters' },
    { location: 'request', label: 'Request body' },
    { location: 'response', label: 'Response body' },
  ];
  return order
    .map(({ location, label }) => ({
      location,
      label,
      fields: operation.fields.filter((field) => field.location === location),
    }))
    .filter((group) => group.fields.length > 0);
}

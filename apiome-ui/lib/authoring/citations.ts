/**
 * Source citations for generated content (UXE-1.3).
 *
 * The roadmap's §28.1 rule is that a proposal rail shows "exact source
 * citations". A citation therefore points at a canonical authoring target —
 * `(canonical_kind, stable_key, source_pointer)` from §3 — not at a page or a
 * vague "the spec". That precision is what lets a reviewer verify a generated
 * sentence instead of trusting it.
 */

/** Canonical target kinds documentation can be written against (roadmap §3). */
export type AuthoringCanonicalKind =
  | 'artifact'
  | 'service'
  | 'operation'
  | 'message'
  | 'channel'
  | 'type'
  | 'field'
  | 'parameter'
  | 'response'
  | 'workflow_step';

/** One cited source location. */
export type AuthoringCitation = {
  id: string;
  /** Human-readable target, e.g. `GET /pets/{petId}`. */
  label: string;
  kind: AuthoringCanonicalKind;
  /** Stable key of the canonical target within its version. */
  stableKey: string;
  /**
   * Pointer into the native source, e.g. a JSON pointer or `file.proto:42`.
   * Absent when the target has no native representation.
   */
  sourcePointer?: string;
  /** Deep link to the target in the Designer, when one exists. */
  href?: string;
  /** Verbatim excerpt the generator relied on, when short enough to show. */
  excerpt?: string;
};

/** Readable names for each canonical kind. */
const KIND_LABELS: Record<AuthoringCanonicalKind, string> = {
  artifact: 'Artifact',
  service: 'Service',
  operation: 'Operation',
  message: 'Message',
  channel: 'Channel',
  type: 'Type',
  field: 'Field',
  parameter: 'Parameter',
  response: 'Response',
  workflow_step: 'Workflow step',
};

/**
 * Readable name for a canonical kind.
 *
 * @param kind - Canonical kind.
 * @returns Title-cased label, e.g. `Workflow step`.
 */
export function describeAuthoringCanonicalKind(kind: AuthoringCanonicalKind): string {
  return KIND_LABELS[kind];
}

/**
 * Format a citation as a single readable location.
 *
 * Used as the citation's accessible name, so a screen-reader user hears where
 * the claim came from without having to open the link.
 *
 * @param citation - Citation to format.
 * @returns e.g. `Operation GET /pets/{petId} at paths./pets/{petId}.get`.
 */
export function formatAuthoringCitation(citation: AuthoringCitation): string {
  const base = `${describeAuthoringCanonicalKind(citation.kind)} ${citation.label}`;
  return citation.sourcePointer ? `${base} at ${citation.sourcePointer}` : base;
}

/**
 * Summarise a citation list for an assistive-technology announcement.
 *
 * A proposal with no citations is a distinct, reportable state rather than an
 * empty list: ungrounded generated text is exactly what a reviewer must be
 * warned about.
 *
 * @param citations - Citations attached to a proposal.
 * @returns A sentence describing how well grounded the proposal is.
 */
export function summarizeAuthoringCitations(citations: readonly AuthoringCitation[]): string {
  if (citations.length === 0) return 'No sources cited. Verify this content before accepting it.';
  if (citations.length === 1) return `1 source cited: ${formatAuthoringCitation(citations[0])}.`;
  return `${citations.length} sources cited.`;
}

/**
 * Suggested changes on a review — COL-4.2 (#4526): the shapes apiome-rest answers with and the pure
 * rules the review page's Suggestions tab is drawn from.
 *
 * A suggestion is an RFC 6902 patch over one element's canonical JSON — `{description, schema}` for
 * a class, `{description, data}` for a property. The reviewer edits one field; {@link buildFieldPatch}
 * turns that edit into the patch. The author applies or rejects it; apiome-rest merges it onto the
 * element as it is now and refuses (`suggestion-stale`) when an edit made since overlaps it.
 */

/** What a suggestion targets. */
export type SuggestionTargetType = 'class' | 'property';

/** Where a suggestion is in its life. */
export type SuggestionStatus = 'open' | 'applied' | 'rejected' | 'stale';

/** One RFC 6902 operation (the subset apiome-rest accepts). */
export interface PatchOp {
  op: 'add' | 'remove' | 'replace' | 'test';
  path: string;
  value?: unknown;
}

/** A stored suggestion. */
export interface ReviewSuggestion {
  id: string;
  review_id: string;
  version_id: string;
  author_id: string | null;
  author_name: string | null;
  target_type: SuggestionTargetType;
  target_id: string;
  target_label: string;
  note: string | null;
  base: Record<string, unknown>;
  patch: PatchOp[];
  proposed: Record<string, unknown>;
  status: SuggestionStatus;
  conflict_paths: string[];
  /** For an open suggestion: applying it would conflict with an edit made since. */
  stale: boolean;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  reason: string | null;
  created_at: string;
}

/** An element a reviewer can suggest a change to, with its canonical JSON. */
export interface SuggestionTarget {
  type: SuggestionTargetType;
  id: string;
  /** `Pet` or `Pet.name`. */
  label: string;
  element: Record<string, unknown>;
}

/** What the Suggestions tab reads. */
export interface SuggestionsPayload {
  suggestions: ReviewSuggestion[];
  /** Whether the viewer may apply or reject others' suggestions. */
  canDecide: boolean;
  /** Elements of the reviewed version (empty when they could not be read). */
  targets: SuggestionTarget[];
}

/** The body key of each target type's JSON; `description` sits beside it. */
export const BODY_KEY: Readonly<Record<SuggestionTargetType, 'schema' | 'data'>> = {
  class: 'schema',
  property: 'data',
};

/** The fields the form offers, by target type. `description` is the element's own description. */
export const SUGGESTABLE_FIELDS: Readonly<Record<SuggestionTargetType, readonly string[]>> = {
  class: ['description', 'type', 'required', 'additionalProperties', 'title'],
  property: ['description', 'type', 'format', 'enum', 'pattern', 'minLength', 'maxLength', 'minimum', 'maximum', 'default', 'example', 'nullable'],
};

/** The most targets the picker lists. */
export const MAX_TARGETS = 500;

/**
 * Escape one JSON-pointer token (RFC 6901).
 *
 * @param token - A key.
 * @returns The token with `~` and `/` escaped.
 */
export function escapePointer(token: string): string {
  return token.replace(/~/g, '~0').replace(/\//g, '~1');
}

/**
 * The JSON pointer of a field of an element.
 *
 * @param type - The target type.
 * @param field - `description` or a key of the schema/data.
 * @returns e.g. `/description` or `/data/maxLength`.
 */
export function fieldPointer(type: SuggestionTargetType, field: string): string {
  return field === 'description' ? '/description' : `/${BODY_KEY[type]}/${escapePointer(field)}`;
}

/**
 * The current value of a field of an element.
 *
 * @param target - The element.
 * @param field - The field.
 * @returns The value, or undefined when the field is absent.
 */
export function currentFieldValue(target: SuggestionTarget, field: string): unknown {
  if (field === 'description') return target.element.description ?? undefined;
  const body = target.element[BODY_KEY[target.type]];
  return body && typeof body === 'object' ? (body as Record<string, unknown>)[field] : undefined;
}

/**
 * Parse what a reviewer typed as a field's new value.
 *
 * `description` is always text. Anything else is read as JSON when it parses (so `100`, `true`,
 * `["a","b"]` and `"text"` mean what they look like) and as plain text otherwise. An empty input
 * means "remove the field".
 *
 * @param field - The field.
 * @param raw - The input.
 * @returns `{remove: true}` or `{value}`.
 */
export function parseFieldInput(field: string, raw: string): { remove: true } | { remove: false; value: unknown } {
  const text = raw.trim();
  if (text === '') return { remove: true };
  if (field === 'description') return { remove: false, value: raw };
  try {
    return { remove: false, value: JSON.parse(text) };
  } catch {
    return { remove: false, value: raw };
  }
}

/**
 * Turn one field edit into a patch: a `test` of the old value (so a stale proposal is caught when it
 * is made, not only when applied) followed by `replace`, `add`, or `remove`.
 *
 * @param target - The element.
 * @param field - The field.
 * @param raw - What the reviewer typed (empty to remove the field).
 * @returns The patch, or null when the edit changes nothing (or removes an absent field).
 */
export function buildFieldPatch(target: SuggestionTarget, field: string, raw: string): PatchOp[] | null {
  const path = fieldPointer(target.type, field);
  const current = currentFieldValue(target, field);
  const parsed = parseFieldInput(field, raw);
  const exists = current !== undefined;
  if (parsed.remove) {
    if (!exists) return null;
    if (field === 'description') return [{ op: 'test', path, value: current }, { op: 'replace', path, value: null }];
    return [{ op: 'test', path, value: current }, { op: 'remove', path }];
  }
  if (exists && JSON.stringify(current) === JSON.stringify(parsed.value)) return null;
  if (!exists) {
    return field === 'description' ? [{ op: 'replace', path, value: parsed.value }] : [{ op: 'add', path, value: parsed.value }];
  }
  return [{ op: 'test', path, value: current }, { op: 'replace', path, value: parsed.value }];
}

/**
 * The input text that shows a field's current value.
 *
 * @param value - The value.
 * @returns Text for the input (JSON for anything that is not a string).
 */
export function fieldInputText(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/**
 * Pretty JSON for the diff viewer.
 *
 * @param value - An element.
 * @returns Two-space JSON.
 */
export function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

/** The label each status shows. */
export const SUGGESTION_STATUS_LABELS: Readonly<Record<SuggestionStatus, string>> = {
  open: 'Open',
  applied: 'Applied',
  rejected: 'Rejected',
  stale: 'Stale',
};

/**
 * What a suggestion's state reads as.
 *
 * @param s - The suggestion.
 * @returns The status label, with `Stale` for an open suggestion that would conflict.
 */
export function suggestionStatusLabel(s: ReviewSuggestion): string {
  return s.status === 'open' && s.stale ? 'Stale' : SUGGESTION_STATUS_LABELS[s.status];
}

/**
 * The sentence under a decided or stale suggestion.
 *
 * @param s - The suggestion.
 * @returns e.g. `Applied by Rita`, `Rejected by Rita: Keep 50`, or the conflict explanation.
 */
export function suggestionOutcome(s: ReviewSuggestion): string | null {
  const who = s.decided_by_name ?? 'someone';
  if (s.status === 'applied') return `Applied by ${who}`;
  if (s.status === 'rejected') return `Rejected by ${who}${s.reason ? `: ${s.reason}` : ''}`;
  if (s.status === 'stale' || s.stale) {
    const paths = s.conflict_paths.includes('<deleted>')
      ? 'the element was deleted'
      : `changed since: ${s.conflict_paths.join(', ')}`;
    return `Can't be applied — ${paths}. Suggest it again against the current version.`;
  }
  return null;
}

/**
 * Which actions a viewer sees on one suggestion.
 *
 * @param s - The suggestion.
 * @param viewerId - The signed-in user.
 * @param canDecide - Whether the viewer is the review's requester or an editor.
 * @returns Whether **Apply** and **Reject** (or **Withdraw**, for the author) are shown, and
 *   whether Apply is enabled.
 */
export function suggestionActions(
  s: ReviewSuggestion,
  viewerId: string | null,
  canDecide: boolean
): { apply: boolean; applyEnabled: boolean; reject: boolean; rejectLabel: 'Reject' | 'Withdraw' } {
  const isAuthor = Boolean(viewerId) && s.author_id === viewerId;
  if (s.status !== 'open') return { apply: false, applyEnabled: false, reject: false, rejectLabel: 'Reject' };
  return {
    apply: canDecide && !isAuthor,
    applyEnabled: !s.stale,
    reject: canDecide || isAuthor,
    rejectLabel: isAuthor ? 'Withdraw' : 'Reject',
  };
}

/** A user-facing message for each apiome-rest suggestion refusal. */
export const SUGGESTION_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  'suggestion-stale': 'The element changed since this was suggested, so it was not applied. It is now marked stale.',
  'suggestion-not-open': 'This suggestion was already decided.',
  'suggestion-forbidden': 'You cannot do that with this suggestion.',
  'suggestion-invalid-patch': 'That change cannot be applied to this element.',
  'suggestion-target-not-found': 'That element is no longer in this version.',
  'review-closed': 'This review was withdrawn.',
  'review-version-published': 'The version is published and can no longer change.',
};

/**
 * Turn a class list from `with-properties-tags` into picker targets.
 *
 * @param classes - The REST reply.
 * @returns Classes and their top-level properties, capped at {@link MAX_TARGETS}.
 */
export function targetsFromClasses(classes: unknown): SuggestionTarget[] {
  if (!Array.isArray(classes)) return [];
  const out: SuggestionTarget[] = [];
  for (const c of classes as Array<Record<string, unknown>>) {
    if (typeof c?.id !== 'string' || typeof c?.name !== 'string') continue;
    out.push({
      type: 'class',
      id: c.id,
      label: c.name,
      element: { description: c.description ?? null, schema: asObject(c.schema) },
    });
    const props = Array.isArray(c.properties) ? (c.properties as Array<Record<string, unknown>>) : [];
    for (const p of props) {
      if (typeof p?.id !== 'string' || typeof p?.name !== 'string' || p.parent_id) continue;
      out.push({
        type: 'property',
        id: p.id,
        label: `${c.name}.${p.name}`,
        element: { description: p.description ?? null, data: asObject(p.data) },
      });
    }
    if (out.length >= MAX_TARGETS) break;
  }
  return out.slice(0, MAX_TARGETS);
}

function asObject(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try {
      return asObject(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

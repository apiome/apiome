/**
 * The overlay manager's editable model — COA-2.7 (#7050).
 *
 * The **New overlay** / **Edit overlay** dialog edits an Overlay 1.0 / 1.1 / 1.2 document as a
 * list of actions — **Update**, **Remove**, **Copy** (1.1) and **Reusable** (a 1.2
 * `components.actions` reference) — plus the overlay's name, revision and title. This module turns a
 * document into that form and back, checks the form before anything is sent, and words the preview's
 * per-action match counts and before / after values. Pure: no React, no fetch.
 *
 * Anything the form does not edit is kept as it was: the document's other top-level keys
 * (`extends`, `components`, `x-` extensions, `info.version`, …) and each action's other keys.
 */

import type { OverlayActionOutcome, OverlayDiffRow, VersionOverlayPreview } from './versionOverlaysApi';

/** What an action does. `ref` is a reusable action (`$ref: '#/components/actions/<name>'`). */
export type OverlayActionKind = 'update' | 'remove' | 'copy' | 'ref';

/** Readable names for {@link OverlayActionKind}, as the dialog shows them. */
export const ACTION_KIND_LABEL: Record<OverlayActionKind, string> = {
  update: 'Update',
  remove: 'Remove',
  copy: 'Copy',
  ref: 'Reusable',
};

/** The Overlay revisions the dialog offers, oldest first. */
export const OVERLAY_REVISIONS = ['1.0.0', '1.1.0', '1.2.0'] as const;

/** The revision a new overlay starts at: 1.1 is the first with `copy`. */
export const DEFAULT_OVERLAY_REVISION = '1.1.0';

/** The JSON Pointer prefix of a reusable action reference. */
const REF_PREFIX = '#/components/actions/';

/** Action keys the form edits; every other key rides along in {@link OverlayActionDraft.extra}. */
const EDITED_ACTION_KEYS = new Set(['target', 'description', 'update', 'copy', 'remove', '$ref']);

/** Longest value text a diff cell shows before it is cut. */
export const MAX_VALUE_TEXT = 160;

/** One action as the dialog edits it. */
export interface OverlayActionDraft {
  /** A stable React key (not part of the document). */
  key: string;
  kind: OverlayActionKind;
  /** The JSONPath expression the action selects. */
  target: string;
  /** Optional note on what the action is for. */
  description: string;
  /** `update` only: the value merged into each match, as JSON text. */
  update: string;
  /** `copy` only: the JSONPath of the one node whose value is copied. */
  copy: string;
  /** `ref` only: the reusable action's name in `components.actions`. */
  ref: string;
  /** The action's other keys (for example `x-` extensions), kept unchanged. */
  extra: Record<string, unknown>;
}

/** The whole overlay as the dialog edits it. */
export interface OverlayDraft {
  /** The stored overlay's label in the chain. */
  name: string;
  /** The `overlay` marker (`1.1.0`). */
  version: string;
  /** `info.title`. */
  title: string;
  actions: OverlayActionDraft[];
  /** Every other top-level key of the document, `info` included (its title is {@link title}). */
  rest: Record<string, unknown>;
}

/** A problem with one field of the form. */
export interface OverlayDraftProblem {
  /** The action's index, or `-1` for the overlay's own fields. */
  index: number;
  field: 'name' | 'title' | 'version' | 'target' | 'update' | 'copy' | 'ref' | 'actions';
  message: string;
}

/** The outcome of {@link draftToDocument}. */
export type OverlayDocumentResult =
  { ok: true; document: Record<string, unknown> } | { ok: false; problems: OverlayDraftProblem[] };

let keySeq = 0;

/** A fresh React key for an action row. */
function nextKey(): string {
  keySeq += 1;
  return `ovl-action-${keySeq}`;
}

/** Whether a value is a plain JSON object. */
function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/**
 * A blank action of a kind.
 *
 * @param kind What the action does (default `update`).
 * @returns The action, with an empty target and `{}` as its update value.
 */
export function blankAction(kind: OverlayActionKind = 'update'): OverlayActionDraft {
  return {
    key: nextKey(),
    kind,
    target: '',
    description: '',
    update: '{}',
    copy: '',
    ref: '',
    extra: {},
  };
}

/**
 * The form a **New overlay** starts with: revision 1.1, one empty **Update** action.
 *
 * @returns The draft.
 */
export function newOverlayDraft(): OverlayDraft {
  return {
    name: '',
    version: DEFAULT_OVERLAY_REVISION,
    title: '',
    actions: [blankAction('update')],
    rest: { info: { version: '1.0.0' } },
  };
}

/**
 * Read one action of a document into the form.
 *
 * @param action One entry of the document's `actions`.
 * @returns The editable action. An action that is not an object becomes an empty **Update**.
 */
function actionToDraft(action: unknown): OverlayActionDraft {
  const draft = blankAction('update');
  if (!isRecord(action)) return draft;
  draft.target = typeof action.target === 'string' ? action.target : '';
  draft.description = typeof action.description === 'string' ? action.description : '';
  for (const [key, value] of Object.entries(action)) {
    if (!EDITED_ACTION_KEYS.has(key)) draft.extra[key] = value;
  }
  const ref = action.$ref;
  if (typeof ref === 'string') {
    draft.kind = 'ref';
    draft.ref = ref.startsWith(REF_PREFIX) ? ref.slice(REF_PREFIX.length).replace(/~1/g, '/').replace(/~0/g, '~') : ref;
  } else if (action.remove === true) {
    draft.kind = 'remove';
  } else if ('copy' in action) {
    draft.kind = 'copy';
    draft.copy = typeof action.copy === 'string' ? action.copy : '';
  } else {
    draft.kind = 'update';
    draft.update = 'update' in action ? JSON.stringify(action.update, null, 2) : '{}';
  }
  return draft;
}

/**
 * Read an Overlay document into the form.
 *
 * @param name The overlay's label in the chain.
 * @param document The Overlay document.
 * @returns The draft; {@link draftToDocument} gives back an equivalent document.
 */
export function documentToDraft(name: string, document: Record<string, unknown>): OverlayDraft {
  const { overlay, actions, ...rest } = document;
  const info = isRecord(rest.info) ? rest.info : {};
  return {
    name,
    version: typeof overlay === 'string' ? overlay : DEFAULT_OVERLAY_REVISION,
    title: typeof info.title === 'string' ? info.title : '',
    actions: Array.isArray(actions) ? actions.map(actionToDraft) : [],
    rest: { ...rest, info: { ...info } },
  };
}

/**
 * The `major.minor` of an overlay marker as a comparable number (`1.10` → 1.1).
 *
 * @param version The marker (`1.1.0`).
 * @returns `major + minor / 100`, or 0 when the marker is not a version.
 */
function revisionNumber(version: string): number {
  const match = /^(\d+)\.(\d+)/.exec(version.trim());
  return match ? Number(match[1]) + Number(match[2]) / 100 : 0;
}

/**
 * The reusable actions the overlay declares (`components.actions` names).
 *
 * @param draft The draft.
 * @returns The names, in document order.
 */
export function reusableActionNames(draft: OverlayDraft): string[] {
  const components = draft.rest.components;
  const actions = isRecord(components) ? components.actions : undefined;
  return isRecord(actions) ? Object.keys(actions) : [];
}

/**
 * The oldest revision an action kind needs.
 *
 * @param kind The action kind.
 * @returns `1.1.0` for copy, `1.2.0` for a reusable action, else `1.0.0`.
 */
export function revisionFor(kind: OverlayActionKind): string {
  return kind === 'copy' ? '1.1.0' : kind === 'ref' ? '1.2.0' : '1.0.0';
}

/**
 * Check the form and build the Overlay document it describes.
 *
 * @param draft The form.
 * @returns The document, or every problem found (each tied to its field).
 */
export function draftToDocument(draft: OverlayDraft): OverlayDocumentResult {
  const problems: OverlayDraftProblem[] = [];
  if (!draft.name.trim()) problems.push({ index: -1, field: 'name', message: 'Name the overlay.' });
  if (!draft.title.trim())
    problems.push({
      index: -1,
      field: 'title',
      message: 'Give the overlay a title.',
    });
  const revision = revisionNumber(draft.version);
  if (!revision)
    problems.push({
      index: -1,
      field: 'version',
      message: 'Choose an Overlay version.',
    });
  if (draft.actions.length === 0) {
    problems.push({
      index: -1,
      field: 'actions',
      message: 'Add at least one action.',
    });
  }
  const reusable = new Set(reusableActionNames(draft));

  const actions = draft.actions.map((action, index) => {
    const out: Record<string, unknown> = {};
    const target = action.target.trim();
    if (!target)
      problems.push({
        index,
        field: 'target',
        message: 'Enter a JSONPath target, for example $.info.',
      });
    else if (!target.startsWith('$')) {
      problems.push({
        index,
        field: 'target',
        message: 'A JSONPath target starts with $.',
      });
    }
    out.target = target;
    if (action.description.trim()) out.description = action.description.trim();
    if (revision && revision < revisionNumber(revisionFor(action.kind))) {
      problems.push({
        index,
        field: action.kind === 'ref' ? 'ref' : action.kind === 'copy' ? 'copy' : 'target',
        message: `${ACTION_KIND_LABEL[action.kind]} needs Overlay ${revisionFor(action.kind).slice(0, 3)} or later.`,
      });
    }
    if (action.kind === 'remove') {
      out.remove = true;
    } else if (action.kind === 'copy') {
      const from = action.copy.trim();
      if (!from.startsWith('$')) {
        problems.push({
          index,
          field: 'copy',
          message: 'Enter the JSONPath of the one value to copy.',
        });
      }
      out.copy = from;
    } else if (action.kind === 'ref') {
      if (!action.ref.trim())
        problems.push({
          index,
          field: 'ref',
          message: 'Choose a reusable action.',
        });
      else if (!reusable.has(action.ref)) {
        problems.push({
          index,
          field: 'ref',
          message: `This overlay declares no reusable action "${action.ref}".`,
        });
      }
      out.$ref = `${REF_PREFIX}${action.ref.replace(/~/g, '~0').replace(/\//g, '~1')}`;
    } else {
      try {
        out.update = JSON.parse(action.update);
      } catch {
        problems.push({
          index,
          field: 'update',
          message: 'The value must be JSON, for example {"description": "…"}.',
        });
      }
    }
    return { ...out, ...action.extra };
  });

  if (problems.length > 0) return { ok: false, problems };
  const info = isRecord(draft.rest.info) ? draft.rest.info : {};
  return {
    ok: true,
    document: {
      overlay: draft.version.trim(),
      ...draft.rest,
      info: {
        ...info,
        title: draft.title.trim(),
        version: typeof info.version === 'string' ? info.version : '1.0.0',
      },
      actions,
    },
  };
}

/**
 * Parse the dialog's **JSON** view back into the form.
 *
 * @param name The overlay's label.
 * @param text The document as JSON text.
 * @returns The draft, or the reason the text is not an Overlay document.
 */
export function parseDraftJson(
  name: string,
  text: string
): { ok: true; draft: OverlayDraft } | { ok: false; error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: 'The document is not valid JSON.' };
  }
  if (!isRecord(parsed) || typeof parsed.overlay !== 'string') {
    return {
      ok: false,
      error: 'An Overlay document is a JSON object with an "overlay" version, such as "1.1.0".',
    };
  }
  return { ok: true, draft: documentToDraft(name, parsed) };
}

/**
 * The preview's outcome rows for one overlay, keyed by action index.
 *
 * @param preview The preview reply.
 * @param overlayLabel The overlay's label in the report (`stored:<name>` / `draft:<name>`).
 * @returns `action_index → outcome`.
 */
export function outcomesFor(
  preview: VersionOverlayPreview | null,
  overlayLabel: string | null | undefined
): Map<number, OverlayActionOutcome> {
  const rows = new Map<number, OverlayActionOutcome>();
  if (!preview?.report?.actions || !overlayLabel) return rows;
  for (const outcome of preview.report.actions) {
    if (outcome.overlay === overlayLabel) rows.set(outcome.action_index, outcome);
  }
  return rows;
}

/**
 * How an action's match count reads (`3 matches`, `No match`, `Not applied`).
 *
 * @param outcome The action's outcome.
 * @returns The words.
 */
export function matchSummary(outcome: OverlayActionOutcome): string {
  if (outcome.status === 'invalid') return 'Not applied';
  if (outcome.matches === 0) return 'No match';
  return `${outcome.matches} ${outcome.matches === 1 ? 'match' : 'matches'}`;
}

/**
 * The tone a match count is shown in.
 *
 * @param outcome The action's outcome.
 * @returns `danger` (refused), `warn` (matched nothing) or `ok`.
 */
export function matchTone(outcome: OverlayActionOutcome): 'danger' | 'warn' | 'ok' {
  if (outcome.status === 'invalid') return 'danger';
  if (outcome.status === 'unmatched' || outcome.matches === 0) return 'warn';
  return 'ok';
}

/**
 * A before / after value as one short line.
 *
 * @param value The value.
 * @param present False when there is no value (added or removed).
 * @returns Compact JSON (strings unquoted), cut at {@link MAX_VALUE_TEXT} characters, or `—`.
 */
export function formatDiffValue(value: unknown, present: boolean): string {
  if (!present) return '—';
  const text = typeof value === 'string' ? value : JSON.stringify(value);
  return text.length > MAX_VALUE_TEXT ? `${text.slice(0, MAX_VALUE_TEXT - 1)}…` : text;
}

/**
 * Who changed a value, as one line (`partner.yaml, action 2`; several writers joined with `→`).
 *
 * @param row The diff row.
 * @returns The provenance line.
 */
export function changedByLabel(row: OverlayDiffRow): string {
  return row.changed_by
    .map((writer) => {
      const name = (writer.overlay ?? '').replace(/^(stored|draft):/, '');
      return writer.action_index === null ? name : `${name}, action ${writer.action_index + 1}`;
    })
    .join(' → ');
}

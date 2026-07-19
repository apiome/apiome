/**
 * Shell state badges (UXE-1.2).
 *
 * Every Authoring surface reports the same operational states through one
 * vocabulary, so "Conflict" means the same thing and looks the same in Scribe,
 * Slate, Releases and Insights.
 *
 * Two rules from the roadmap's accessibility constraints are enforced here
 * rather than left to each renderer: every badge carries a text label and an
 * icon, so status is never conveyed by color alone; and every badge carries a
 * sentence explaining what the state means and what the viewer can do.
 */

/** Identifier of a shell state. */
export type AuthoringStateId =
  'offline' | 'conflict' | 'unentitled' | 'read-only' | 'unsaved' | 'saving' | 'loading' | 'saved';

/** Semantic tone used to pick a badge's palette. Never the only signal. */
export type AuthoringStateTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

/** One rendered state badge. */
export type AuthoringStateBadge = {
  id: AuthoringStateId;
  /** Short visible label, e.g. `Conflict`. */
  label: string;
  /** Sentence explaining the state and the way out of it. */
  description: string;
  tone: AuthoringStateTone;
  /** Lucide icon name, resolved on the client. */
  icon: string;
  /**
   * True when the state needs to be announced as it happens rather than only
   * when the region is read. Drives `aria-live="assertive"`.
   */
  urgent: boolean;
};

/** Everything the shell needs to derive its badges. */
export type AuthoringStateInput = {
  /** False when the browser reports no network connection. */
  online: boolean;
  /** True while scope data or surface content is still resolving. */
  loading: boolean;
  /** True when a remote change conflicts with local edits. */
  conflict: boolean;
  /** True when there are edits not yet persisted. */
  unsavedChanges: boolean;
  /** True while a save is in flight. */
  saving: boolean;
  /** True when the selected scope cannot be edited. */
  readOnly: boolean;
  /** False when the viewer lacks the license the current surface requires. */
  entitled: boolean;
};

/** Default input: idle, online, editable and entitled. */
export const IDLE_AUTHORING_STATE: AuthoringStateInput = {
  online: true,
  loading: false,
  conflict: false,
  unsavedChanges: false,
  saving: false,
  readOnly: false,
  entitled: true,
};

/** Canonical descriptor for each state. */
const BADGES: Record<AuthoringStateId, AuthoringStateBadge> = {
  offline: {
    id: 'offline',
    label: 'Offline',
    description: 'You are offline. Changes are kept locally and sent when the connection returns.',
    tone: 'danger',
    icon: 'CloudOff',
    urgent: true,
  },
  conflict: {
    id: 'conflict',
    label: 'Conflict',
    description:
      'Someone else changed this since you loaded it. Review both versions before saving.',
    tone: 'danger',
    icon: 'GitMerge',
    urgent: true,
  },
  unentitled: {
    id: 'unentitled',
    label: 'No access',
    description: 'Your plan does not include this area. Ask a tenant admin to enable it.',
    tone: 'warning',
    icon: 'Lock',
    urgent: false,
  },
  'read-only': {
    id: 'read-only',
    label: 'Read only',
    description: 'This scope cannot be edited. Select a draft version or the preview environment.',
    tone: 'info',
    icon: 'Eye',
    urgent: false,
  },
  unsaved: {
    id: 'unsaved',
    label: 'Unsaved changes',
    description: 'Edits are not saved yet.',
    tone: 'warning',
    icon: 'CircleDot',
    urgent: false,
  },
  saving: {
    id: 'saving',
    label: 'Saving',
    description: 'Saving your changes.',
    tone: 'info',
    icon: 'LoaderCircle',
    urgent: false,
  },
  loading: {
    id: 'loading',
    label: 'Loading',
    description: 'Loading the current scope.',
    tone: 'neutral',
    icon: 'LoaderCircle',
    urgent: false,
  },
  saved: {
    id: 'saved',
    label: 'Saved',
    description: 'All changes are saved.',
    tone: 'success',
    icon: 'Check',
    urgent: false,
  },
};

/**
 * Look up a badge descriptor by id.
 *
 * @param id - State id.
 * @returns The descriptor for `id`.
 */
export function getAuthoringStateBadge(id: AuthoringStateId): AuthoringStateBadge {
  return BADGES[id];
}

/**
 * Derive the badges to show for the current shell state.
 *
 * Blocking states come first and suppress the save pipeline below them: while
 * offline or in conflict, reporting "Saved" would be a lie, and reporting
 * "Saving" would suggest progress that is not happening. Read-only and
 * entitlement are shown alongside, because they explain *why* editing is
 * unavailable rather than describing an operation in flight.
 *
 * At most one save-pipeline badge is returned, in precedence order
 * conflict → unsaved → saving → loading → saved.
 *
 * @param input - Current shell state.
 * @returns Ordered badges, most urgent first. Never empty.
 */
export function resolveAuthoringStateBadges(input: AuthoringStateInput): AuthoringStateBadge[] {
  const badges: AuthoringStateBadge[] = [];

  if (!input.online) badges.push(BADGES.offline);
  if (input.conflict) badges.push(BADGES.conflict);
  if (!input.entitled) badges.push(BADGES.unentitled);
  if (input.readOnly) badges.push(BADGES['read-only']);

  const blocked = !input.online || input.conflict;
  if (!blocked) {
    if (input.unsavedChanges) badges.push(BADGES.unsaved);
    else if (input.saving) badges.push(BADGES.saving);
    else if (input.loading) badges.push(BADGES.loading);
  }

  // Something must always be reported, so the status region is never silent.
  if (badges.length === 0) badges.push(BADGES.saved);

  return badges;
}

/**
 * True when any badge in the list must be announced immediately.
 *
 * @param badges - Badges currently shown.
 */
export function hasUrgentAuthoringState(badges: readonly AuthoringStateBadge[]): boolean {
  return badges.some((badge) => badge.urgent);
}

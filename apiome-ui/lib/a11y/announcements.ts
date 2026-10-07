/**
 * Live-region sentences — what a screen reader hears when status changes on its own
 * (HIVE-10.2, #5338, `docs/mockups/DESIGN.md` §9).
 *
 * Every surface that polls or saves in the background renders a `ui/LiveRegion` and passes it
 * one of these sentences. Keeping the wording here gives every surface the same voice, keeps the
 * sentences coarse (a reader hears a change of *state*, never every percent tick) and makes them
 * testable without rendering anything.
 */

/** Progress of a multi-step job, as the import status endpoint reports it. */
export interface StepProgress {
  /** Steps finished. */
  completed: number;
  /** Steps in total; `0` when the job has not planned its steps yet. */
  total: number;
}

/**
 * The sentence for an import job's state.
 *
 * @param label The job's state as the status badge shows it, e.g. `Running`, `Completed`.
 * @param progress Step progress, when known. Only whole steps are announced.
 * @returns e.g. `Import running: step 3 of 8`, or `Import completed`.
 */
export function importJobAnnouncement(label: string, progress?: StepProgress | null): string {
  const state = label.trim().toLowerCase();
  if (!state) return '';
  const steps = progress && progress.total > 0 ? `: step ${progress.completed} of ${progress.total}` : '';
  return `Import ${state}${steps}`;
}

/** The fields of a repository the settle announcement reads. */
export interface RepositoryStatusRow {
  id: string;
  name: string;
  status: string;
}

/** Repository statuses that mean "still registering or scanning". */
const IN_FLIGHT_REPOSITORY_STATUSES = new Set(['pending', 'scanning']);

/** What a settled repository status sounds like. */
const SETTLED_REPOSITORY_PHRASE: Record<string, string> = {
  ready: 'is ready',
  error: 'failed to scan',
  archived: 'was archived',
};

/**
 * The sentence for repositories that finished registering or scanning since the last poll.
 *
 * @param previous Each repository's status at the previous poll, by id. Repositories that were
 *   not in flight then (or are new) are ignored, so a first load announces nothing.
 * @param next The repositories as the latest poll returned them.
 * @returns e.g. `acme/api is ready`, `3 repositories finished scanning`, or `''` when nothing
 *   settled.
 */
export function settledRepositoriesAnnouncement(
  previous: ReadonlyMap<string, string>,
  next: readonly RepositoryStatusRow[],
): string {
  const settled = next.filter(
    (repository) =>
      IN_FLIGHT_REPOSITORY_STATUSES.has(previous.get(repository.id) ?? '') &&
      !IN_FLIGHT_REPOSITORY_STATUSES.has(repository.status),
  );
  if (settled.length === 0) return '';
  if (settled.length === 1) {
    const [repository] = settled;
    return `${repository.name} ${SETTLED_REPOSITORY_PHRASE[repository.status] ?? `is ${repository.status}`}`;
  }
  return `${settled.length} repositories finished scanning`;
}

/** A form's save state. */
export interface SaveState {
  /** A save request is in flight. */
  saving: boolean;
  /** There are edits the server has not seen. */
  dirty: boolean;
  /** The last save failed (its message is shown elsewhere, in an alert). */
  failed?: boolean;
}

/**
 * The sentence for a form's save state.
 *
 * @param state The save state.
 * @returns `Saving…`, `Save failed`, `Unsaved changes`, or `All changes saved`.
 */
export function saveStateAnnouncement(state: SaveState): string {
  if (state.saving) return 'Saving…';
  if (state.failed) return 'Save failed';
  if (state.dirty) return 'Unsaved changes';
  return 'All changes saved';
}

/**
 * The sentence for a filtered list's result count (command palette, search boxes).
 *
 * @param count Results shown.
 * @param query The query typed; an empty query announces nothing (the list is the default one).
 * @returns e.g. `No results`, `1 result`, `12 results`, or `''`.
 */
export function resultCountAnnouncement(count: number, query: string): string {
  if (!query.trim()) return '';
  if (count === 0) return 'No results';
  return `${count} result${count === 1 ? '' : 's'}`;
}

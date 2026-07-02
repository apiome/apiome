/**
 * Shared types for the version-action dialogs (Commit / Branch / Tag / Merge / Rollback).
 *
 * These dialogs are self-contained — they fetch their own branch list, own their own
 * form state, and make their own API calls. The consumer just opens them and listens
 * for `onSuccess` when something was persisted so it can refresh its local view.
 */

export interface VersionBranchRow {
  id: string;
  name: string;
  tip_version_id: string;
  tip_version_string?: string;
  created_at?: string;
  created_by?: string | null;
  protected?: boolean;
  /** GLI-01 — exactly one default branch per project. */
  is_default?: boolean;
}

/** Minimal revision shape needed by dialogs for labels and branch-from operations. */
export interface DialogRevisionRef {
  id: string;
  version_id?: string | null;
  shortMessage?: string | null;
  description?: string | null;
}

/** Result passed back to the parent so it can switch to / refresh the newly created revision. */
export interface CreatedRevisionResult {
  id?: string;
  version_id?: string;
  published?: boolean;
}

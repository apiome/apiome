'use client';

import * as React from 'react';

import {
  applyLintFixes,
  fetchLintFixPlan,
  type LintFixApplyResult,
  type LintFixPlan,
} from '@/app/utils/lint-fix';

/**
 * One revision's lint-fix plan and apply — GVM-3.6 (#5874).
 *
 * The state the Lint report dialog's fix controls render: the plan (loaded while `enabled`),
 * the apply in flight, the revision the last apply created, and the last refusal. After a
 * successful apply the plan is read again and `onApplied` runs, so the caller can refresh its
 * stored report and its list of revisions.
 */
export interface RevisionLintFixes {
  /** The plan, once loaded. */
  plan: LintFixPlan | null;
  /** True while the plan is being read. */
  loading: boolean;
  /** Why the plan could not be read (e.g. not an OpenAPI document). */
  error: string | null;
  /** True while an apply is in flight. */
  busy: boolean;
  /** The revision the last apply created. */
  result: LintFixApplyResult | null;
  /** Why the last apply was refused. */
  applyError: string | null;
  /** Apply the named fixes with a reason; resolves once the plan is re-read. */
  apply: (fixIds: readonly string[], reason: string) => Promise<void>;
}

/**
 * Load and apply a revision's lint fixes.
 *
 * @param projectId The project, or null when there is none.
 * @param versionId The revision, or null.
 * @param enabled Load the plan only while true (the dialog is open and the report loaded).
 * @param onApplied Called with the created revision after a successful apply.
 * @returns See {@link RevisionLintFixes}.
 */
export function useRevisionLintFixes(
  projectId: string | null,
  versionId: string | null,
  enabled: boolean,
  onApplied?: (result: LintFixApplyResult) => void,
): RevisionLintFixes {
  const [plan, setPlan] = React.useState<LintFixPlan | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<LintFixApplyResult | null>(null);
  const [applyError, setApplyError] = React.useState<string | null>(null);
  const [generation, setGeneration] = React.useState(0);
  const onAppliedRef = React.useRef(onApplied);
  React.useEffect(() => {
    onAppliedRef.current = onApplied;
  }, [onApplied]);

  // A different revision is a different plan: drop everything held for the previous one.
  React.useEffect(() => {
    setPlan(null);
    setError(null);
    setResult(null);
    setApplyError(null);
  }, [projectId, versionId]);

  React.useEffect(() => {
    if (!enabled || !projectId || !versionId) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchLintFixPlan(projectId, versionId, { signal: controller.signal })
      .then((next) => {
        if (!controller.signal.aborted) setPlan(next);
      })
      .catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setPlan(null);
        setError(caught instanceof Error ? caught.message : 'Could not plan the lint fixes.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [enabled, projectId, versionId, generation]);

  const apply = React.useCallback(
    async (fixIds: readonly string[], reason: string) => {
      if (!projectId || !versionId) return;
      setBusy(true);
      setApplyError(null);
      try {
        const created = await applyLintFixes(projectId, versionId, fixIds, reason);
        setResult(created);
        setGeneration((n) => n + 1);
        onAppliedRef.current?.(created);
      } catch (caught) {
        setApplyError(caught instanceof Error ? caught.message : 'Could not apply the lint fixes.');
      } finally {
        setBusy(false);
      }
    },
    [projectId, versionId],
  );

  return { plan, loading, error, busy, result, applyError, apply };
}

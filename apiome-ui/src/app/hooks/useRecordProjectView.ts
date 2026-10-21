'use client';

/**
 * Record the projects a reader opens, for Home's **Recently viewed** panel (#510).
 *
 * A project counts as *opened* when the reader chose it — when the page's URL names it
 * (`?projectId=`, which every drill-down and the project picker set) and it is the selected
 * project. The Versions page's fallback of selecting the first project when the URL names none is
 * not a choice, so it is not recorded; otherwise every visit to the page would log whichever
 * project sorts first.
 *
 * Each project is recorded once per mount: re-renders, filter changes and tab switches on the
 * same project do not add views, but picking another project and coming back does.
 */

import { useEffect, useRef } from 'react';

import { recordProjectViewForSession } from '@lib/db/project-views';

/** Inputs to {@link useRecordProjectView}. */
export interface UseRecordProjectViewOptions {
  /** The project id the URL names (`?projectId=`), or `null` when it names none. */
  urlProjectId: string | null;
  /** The project the page currently shows, or an empty string / `null` before one is chosen. */
  selectedProjectId: string | null;
}

/**
 * Whether the page is showing a project the reader explicitly opened.
 *
 * @param options See {@link UseRecordProjectViewOptions}.
 * @returns The project id to record, or `null` when nothing should be recorded.
 */
export function projectToRecord({
  urlProjectId,
  selectedProjectId,
}: UseRecordProjectViewOptions): string | null {
  if (!urlProjectId || !selectedProjectId) return null;
  return urlProjectId === selectedProjectId ? selectedProjectId : null;
}

/**
 * Record a view each time the reader opens a different project.
 *
 * Fire-and-forget: the server action never throws and the page never waits on it.
 *
 * @param options See {@link UseRecordProjectViewOptions}.
 */
export function useRecordProjectView(options: UseRecordProjectViewOptions): void {
  const projectId = projectToRecord(options);
  const lastRecorded = useRef<string | null>(null);

  useEffect(() => {
    if (!projectId || lastRecorded.current === projectId) return;
    lastRecorded.current = projectId;
    void recordProjectViewForSession(projectId).catch(() => undefined);
  }, [projectId]);
}

export default useRecordProjectView;

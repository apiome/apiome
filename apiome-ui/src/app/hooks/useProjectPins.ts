'use client';

/**
 * The reader's pinned projects, for the Projects list's ⋯ menus (#513).
 *
 * Loads which projects in the current workspace are pinned, so each menu can say "Pin to Home"
 * or "Unpin from Home", and toggles a pin with a toast that says what happened — including the
 * one refusal a reader can cause, pinning a ninth project.
 */

import { useCallback, useEffect, useState } from 'react';

import { toast } from '@/app/components/ui/toast';
import { PROJECT_PIN_LIMIT, type PinProjectStatus } from '@lib/db/dashboard-home-model';
import {
  listPinnedProjectIdsForSession,
  pinProjectForSession,
  unpinProjectForSession,
} from '@lib/db/project-pins';

/** The toast for one pin attempt. */
export interface PinToast {
  /** `success` for a pin (new or existing), `error` for anything that did not pin. */
  tone: 'success' | 'error';
  /** What to tell the reader. */
  message: string;
}

/**
 * Word the outcome of pinning a project.
 *
 * @param status What {@link pinProjectForSession} reported.
 * @param projectName The project's name, quoted in the message.
 * @returns The toast to show.
 */
export function pinToast(status: PinProjectStatus, projectName: string): PinToast {
  switch (status) {
    case 'pinned':
    case 'already_pinned':
      return { tone: 'success', message: `Pinned "${projectName}" to Home.` };
    case 'limit_reached':
      return {
        tone: 'error',
        message: `You can pin up to ${PROJECT_PIN_LIMIT} projects. Unpin one on Home first.`,
      };
    case 'not_found':
      return { tone: 'error', message: `"${projectName}" can no longer be pinned.` };
    default:
      return { tone: 'error', message: `Could not pin "${projectName}". Try again.` };
  }
}

/** A project, as far as pinning needs to know it. */
export interface PinnableProject {
  /** The project's record id. */
  id: string;
  /** Its name, for the toast. */
  name: string;
}

/** What {@link useProjectPins} returns. */
export interface UseProjectPinsResult {
  /** Whether a project is pinned. */
  isPinned: (projectId: string) => boolean;
  /** Pin an unpinned project, or unpin a pinned one. */
  togglePin: (project: PinnableProject) => Promise<void>;
}

/**
 * Track and toggle the reader's pins in the current workspace.
 *
 * @param tenantId The current workspace; pins are re-read when it changes. `null`/`undefined`
 *   means none, and nothing is pinned.
 * @returns See {@link UseProjectPinsResult}.
 */
export function useProjectPins(tenantId: string | null | undefined): UseProjectPinsResult {
  const [pinned, setPinned] = useState<ReadonlySet<string>>(() => new Set());

  useEffect(() => {
    if (!tenantId) return;
    let cancelled = false;
    void listPinnedProjectIdsForSession()
      .catch(() => [] as string[])
      .then((ids) => {
        if (!cancelled) setPinned(new Set(ids));
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  // With no workspace nothing is pinned, whatever an earlier workspace left in state.
  const isPinned = useCallback(
    (projectId: string) => Boolean(tenantId) && pinned.has(projectId),
    [pinned, tenantId],
  );

  const togglePin = useCallback(
    async (project: PinnableProject) => {
      if (pinned.has(project.id)) {
        const ok = await unpinProjectForSession(project.id).catch(() => false);
        if (ok) {
          setPinned((current) => {
            const next = new Set(current);
            next.delete(project.id);
            return next;
          });
          toast.success(`Unpinned "${project.name}".`);
        } else {
          toast.error(`Could not unpin "${project.name}". Try again.`);
        }
        return;
      }

      const status = await pinProjectForSession(project.id).catch(
        (): PinProjectStatus => 'error',
      );
      if (status === 'pinned' || status === 'already_pinned') {
        setPinned((current) => new Set(current).add(project.id));
      }
      const outcome = pinToast(status, project.name);
      if (outcome.tone === 'success') toast.success(outcome.message);
      else toast.error(outcome.message);
    },
    [pinned],
  );

  return { isPinned, togglePin };
}

export default useProjectPins;

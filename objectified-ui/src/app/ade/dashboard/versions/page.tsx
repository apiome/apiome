/**
 * Versions surface — redirected.
 *
 * Versions used to have a top-level sidebar entry that opened a project
 * picker here. Now that versions live inside each project's Versions tab,
 * the standalone picker is redundant; the canonical entry point is the
 * Projects screen, and per-project history is reached via
 * `/ade/dashboard/projects/[id]?tab=versions`.
 *
 * This page exists only to absorb stale URLs:
 *   - direct bookmarks of `/ade/dashboard/versions`
 *   - legacy git-like callers (BranchRecentTicker, DesignerCanvasGitMenu,
 *     StudioHeader, CanvasHistoryGraphDialog) that still push here with
 *     query params for branch/compare flows; those are FEATURE_GITLIKE-
 *     gated UI today, so the redirect is harmless until the flag flips
 *     and those callers get rewritten against the new per-project surface.
 *
 * Implemented as a server component so the redirect happens before any
 * client JS loads — no flash of intermediate content.
 */

import { redirect } from 'next/navigation';

export default function VersionsRedirectPage() {
  redirect('/ade/dashboard/projects');
}

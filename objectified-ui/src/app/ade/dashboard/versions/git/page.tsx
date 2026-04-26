'use client';

/**
 * Legacy git-like Versions surface.
 *
 * The pre-redesign Versions screen lived at `/ade/dashboard/versions` and
 * carried branches, tags, commit/revision flow, push/pull, change reports —
 * the whole git-like vocabulary. The redesign moves that route to a project
 * picker; this nested route preserves the legacy implementation behind the
 * `FEATURE_GITLIKE` flag so we can re-enable it without resurrecting deleted
 * code.
 *
 * - `FEATURE_GITLIKE === true`  → render the legacy implementation untouched.
 * - `FEATURE_GITLIKE === false` → show a polite "disabled in this build"
 *   panel with a link back to Projects (the canonical entry point now that
 *   the standalone Versions picker has been retired). Same flag the rest of
 *   the git-like UI honours, so it stays consistent without a separate
 *   per-page toggle.
 */

import Link from 'next/link';
import { ArrowLeft, GitBranch, Lock } from 'lucide-react';
import { FEATURE_GITLIKE } from '@lib/feature-flags';
import LegacyGitVersions from '../git-versions-impl';

export default function GitVersionsPage() {
  if (FEATURE_GITLIKE) {
    return <LegacyGitVersions />;
  }

  return (
    <main className="flex-1 overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-8 mt-8">
        <div className="flex items-start gap-4">
          <span
            className="w-12 h-12 rounded-lg flex items-center justify-center bg-gradient-to-br from-slate-400 to-slate-500 text-white shadow-sm shrink-0"
            aria-hidden="true"
          >
            <Lock className="w-6 h-6" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 inline-flex items-center gap-2">
              <GitBranch className="w-5 h-5 text-slate-500" />
              Git-like versioning is disabled
            </h1>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                    Branches, tags, commit/revision flow, push &amp; pull, and the
                    change-report tabs are turned off in this build. The redesigned
                    Versions experience lives inside each project — open a project
                    and switch to the Versions tab.
                  </p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-3 font-mono">
              To re-enable: flip <code>FEATURE_GITLIKE</code> in{' '}
              <code>lib/feature-flags.ts</code>.
            </p>
                  <Link
                    href="/ade/dashboard/projects"
                    className="inline-flex items-center gap-1.5 mt-5 text-sm font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
                  >
                    <ArrowLeft className="w-4 h-4" />
                    Back to Projects
                  </Link>
          </div>
        </div>
      </div>
    </main>
  );
}

'use client';

/**
 * The Versions status strip (HIVE-11.2, #5598) — the three timeline banners and the git-like
 * "server is ahead" banner, folded into one {@link StatusStrip}.
 *
 * Authority: `docs/mockups/proposals/versions-status-strip.html` (annotation 3), which
 * supersedes the stacked banners of `build/versions.html` (HIVE-6.2, #5313). The banners put
 * ≈ 200 px of full-width alerts above the timeline on every visit; the strip is one row of
 * chips with at most one open detail row, so the first revision row comes back above the fold.
 *
 * The statuses are still derived, not fetched, by `versionsModel` from data the screen already
 * holds, and each keeps its old copy and actions verbatim:
 *
 * - **Compatibility** — the newest published revision's stored change classification;
 *   *View report* opens the Changes tab.
 * - **What's new** — the head revision's note; *Open changes* opens the Changes tab.
 * - **Deprecation** — the newest deprecated revision with a sunset or a message;
 *   *Sunset timeline* and *Migration guide ↗* (#507).
 * - **Server ahead** (`FEATURE_GITLIKE` only) — the project's head moved after this reader's
 *   last push; *Pull* and *Open merge*.
 *
 * Any of them may be absent; with none the strip is not rendered. Which chip is open is the
 * reader's choice, remembered per project for the session under
 * `hive.versions.status.<projectId>` ({@link VERSIONS_STATUS_STORAGE_PREFIX}).
 */

import * as React from 'react';
import Link from 'next/link';
import { ArrowUpRight, CloudAlert, Download, GitMerge, ShieldCheck, Sparkles, Sunset, TriangleAlert } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { StatusStrip, type StatusStripItem, type StatusStripTone } from '@/app/components/ui/StatusStrip';
import { MIGRATION_GUIDE_ISSUE_URL } from '@/app/utils/revision-deprecation';

import { GitlikeFlag } from './GitlikeFlag';
import type { CompatibilityBanner, DeprecationBanner, WhatsNewBanner } from './versionsModel';

/** Where the sunset timeline lives. */
export const SUNSET_TIMELINE_ROUTE = '/ade/dashboard/versions/sunset-timeline';

/** The `sessionStorage` namespace of the strip; the project id completes the key. */
export const VERSIONS_STATUS_STORAGE_PREFIX = 'hive.versions.status.';

/** The strip's accessible name. */
export const VERSIONS_STATUS_LABEL = 'Project status';

/** The git-like "server is ahead" status, when the reader's last push is behind the server. */
export interface ServerAheadStatus {
  /** Optional API detail, shown under the main line. */
  detail?: string;
  /** Whether *Pull* is unavailable. */
  pullDisabled?: boolean;
  /** Whether a pull is running (*Pulling…*). */
  pullLoading?: boolean;
  /** Pull the server's head and reconcile. */
  onPull: () => void;
  /** Open the merge dialog. */
  onOpenMerge: () => void;
  /** Draw the honey `gitlike` flag beside the actions (non-production builds). */
  flagged?: boolean;
}

/** Everything the strip says, as the page holds it. */
export interface VersionsStatusInput {
  /** The compatibility status, or `null`. */
  compatibility: CompatibilityBanner | null;
  /** The what's-new status, or `null`. */
  whatsNew: WhatsNewBanner | null;
  /** The deprecation status, or `null`. */
  deprecation: DeprecationBanner | null;
  /** The git-like server-ahead status, or `null` (always `null` without `FEATURE_GITLIKE`). */
  serverAhead: ServerAheadStatus | null;
  /** Whether the Changes tab exists — the two "open changes" actions need it. */
  changesAvailable: boolean;
  /** Switch to the Changes tab. */
  onOpenChanges: () => void;
}

/** Props for {@link VersionsStatusStrip}. */
export interface VersionsStatusStripProps extends VersionsStatusInput {
  /** The selected project — the session key's last segment. `null` forgets on reload. */
  projectId: string | null;
}

/** The strip tone for each compatibility verdict; "pending" and "initial" are information. */
const COMPAT_TONE: Readonly<Record<CompatibilityBanner['tone'], StatusStripTone>> = {
  ok: 'ok',
  warn: 'warn',
  danger: 'danger',
  neutral: 'accent',
};

/**
 * A banner title as a chip label: `Compatible.` → `Compatible`.
 *
 * @param title The detail row's lead sentence.
 * @returns The same words without the closing full stop.
 */
function chipLabel(title: string): string {
  return title.replace(/\.$/, '');
}

/**
 * The strip's statuses in reading order — Compatible · What's new · Deprecated · Server ahead.
 *
 * Pure: the page passes what it already derived and gets back the items `StatusStrip` draws.
 * A status with nothing to say is left out rather than drawn empty.
 *
 * @param input See {@link VersionsStatusInput}.
 * @returns The items, possibly empty.
 */
export function versionsStatusItems({
  compatibility,
  whatsNew,
  deprecation,
  serverAhead,
  changesAvailable,
  onOpenChanges,
}: VersionsStatusInput): StatusStripItem[] {
  const items: StatusStripItem[] = [];

  if (compatibility) {
    items.push({
      id: 'compat',
      tone: COMPAT_TONE[compatibility.tone],
      icon: compatibility.tone === 'ok' ? ShieldCheck : TriangleAlert,
      label: chipLabel(compatibility.title),
      detail: compatibility.pairLabel ?? undefined,
      title: compatibility.title,
      body: compatibility.body,
      actions: changesAvailable ? (
        <Button variant="outline" size="sm" onClick={onOpenChanges}>
          View report
        </Button>
      ) : undefined,
    });
  }

  if (whatsNew) {
    items.push({
      id: 'whats-new',
      tone: 'accent',
      icon: Sparkles,
      label: 'What’s new',
      detail: `${whatsNew.versionLabel} ${whatsNew.status}`,
      title: `What’s new in ${whatsNew.versionLabel} (${whatsNew.status}).`,
      body: whatsNew.summary,
      actions: changesAvailable ? (
        <Button variant="outline" size="sm" onClick={onOpenChanges}>
          Open changes
        </Button>
      ) : undefined,
    });
  }

  if (deprecation) {
    items.push({
      id: 'deprecation',
      tone: 'warn',
      icon: Sunset,
      label: `${deprecation.versionLabel} deprecated`,
      detail: deprecation.sunsetDayLabel ? `· sunset ${deprecation.sunsetDayLabel}` : undefined,
      title: `${deprecation.versionLabel} is deprecated${
        deprecation.sunsetLabel ? ` — sunset ${deprecation.sunsetLabel}.` : '.'
      }`,
      body: (
        <>
          {deprecation.successorLabel ? (
            <>
              Successor <span className="mono">{deprecation.successorLabel}</span>.{' '}
            </>
          ) : null}
          {deprecation.message ? <>{deprecation.message} </> : null}
          Consumers see the same warning on compatibility checks (#507).
        </>
      ),
      actions: (
        <>
          <Button variant="outline" size="sm" asChild>
            <Link href={SUNSET_TIMELINE_ROUTE}>Sunset timeline</Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={MIGRATION_GUIDE_ISSUE_URL} target="_blank" rel="noopener noreferrer">
              Migration guide
              <ArrowUpRight aria-hidden />
            </a>
          </Button>
        </>
      ),
    });
  }

  if (serverAhead) {
    items.push({
      id: 'server-ahead',
      tone: 'warn',
      icon: CloudAlert,
      label: 'Server ahead',
      title: 'Server is ahead of your last push.',
      body: (
        <>
          Pull to integrate or open a merge.
          {serverAhead.detail ? <span className="ver-status__detail">{serverAhead.detail}</span> : null}
        </>
      ),
      actions: (
        <>
          {serverAhead.flagged ? <GitlikeFlag enabled /> : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={serverAhead.pullDisabled || serverAhead.pullLoading}
            onClick={serverAhead.onPull}
          >
            <Download aria-hidden />
            {serverAhead.pullLoading ? 'Pulling…' : 'Pull'}
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={serverAhead.onOpenMerge}>
            <GitMerge aria-hidden />
            Open merge
          </Button>
        </>
      ),
    });
  }

  return items;
}

/**
 * Render the strip. See {@link VersionsStatusStripProps}.
 *
 * @returns The strip, or `null` when no status applies.
 */
export default function VersionsStatusStrip({ projectId, ...input }: VersionsStatusStripProps) {
  const items = versionsStatusItems(input);
  return (
    <StatusStrip
      aria-label={VERSIONS_STATUS_LABEL}
      items={items}
      storageKey={projectId ?? undefined}
      storagePrefix={VERSIONS_STATUS_STORAGE_PREFIX}
    />
  );
}

'use client';

/**
 * The primitive reference gallery (UXE-1.3).
 *
 * Every Authoring primitive, in every state that matters, on one page. It
 * exists to make the acceptance criteria falsifiable:
 *
 * - "Light, dark, high-contrast and reduced-motion references pass" needs a
 *   reference to render. This is it — the Playwright spec screenshots this
 *   route once per theme.
 * - "Downstream screens do not fork status or publish/rollback patterns" is
 *   easier to hold when the canonical rendering is one page a reviewer can look
 *   at before writing a new one.
 *
 * The gallery is a development aid, not a product surface: it is absent from
 * `AUTHORING_SURFACES`, so it never appears in the suite dropdown, the
 * secondary navigation or the command palette.
 */

import * as React from 'react';
import { describeAuthoringProposalStatus } from '@lib/authoring/proposals';
import {
  REFERENCE_BLOCKING_CHECKS,
  REFERENCE_BULK_ACTIONS,
  REFERENCE_CHECKS,
  REFERENCE_DIFF,
  REFERENCE_FAILED_PHASES,
  REFERENCE_PASSING_CHECKS,
  REFERENCE_PHASES,
  REFERENCE_PROMOTE_SHEET,
  REFERENCE_PROPOSAL,
  REFERENCE_PROPOSAL_STATUSES,
  REFERENCE_PURGE_SHEET,
  REFERENCE_RISKY_PROPOSAL,
  REFERENCE_SERIES,
  REFERENCE_SPARSE_SERIES,
  REFERENCE_TREE,
} from '@lib/authoring/reference-fixtures';
import { AUTHORING_TONES } from '@lib/authoring/tokens';
import {
  authoringContentClass,
  authoringMutedTextClass,
  authoringSectionTitleClass,
  authoringSurfaceClass,
} from '../authoringClasses';
import {
  AuthoringAnalyticsPanel,
  AuthoringCheckSummary,
  AuthoringContentTree,
  AuthoringDiffView,
  AuthoringEnvironmentBadge,
  AuthoringImpactSheet,
  AuthoringPeekDrawer,
  AuthoringProgressPhases,
  AuthoringProposalCard,
  AuthoringReleaseBadge,
  AuthoringSelectionBar,
  AuthoringSplitWorkspace,
  AuthoringToneBadge,
} from './primitives';
import { describeAuthoringRelease, type AuthoringReleaseStatus } from '@lib/authoring/releases';

/** Every release status, so the timeline vocabulary is shown in full. */
const RELEASE_STATUSES: readonly AuthoringReleaseStatus[] = [
  'queued',
  'building',
  'ready',
  'review',
  'active',
  'superseded',
  'failed',
  'rolled-back',
] as const;

/**
 * Render the full primitive reference.
 */
export default function AuthoringReferenceGallery() {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set(['guides', 'pets']));
  const [selectedNode, setSelectedNode] = React.useState('pets-get');
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [promoteOpen, setPromoteOpen] = React.useState(false);
  const [purgeOpen, setPurgeOpen] = React.useState(false);
  const [selectedCount, setSelectedCount] = React.useState(3);

  return (
    <div className={authoringContentClass} data-testid="authoring-reference-gallery">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-white">
          Authoring primitive reference
        </h1>
        <p className={authoringMutedTextClass}>
          Every shared primitive in every state it supports. Authoring workspaces render these
          rather than defining their own status or publish patterns. Switch the theme to check the
          light, dark and high-contrast references.
        </p>
      </header>

      <Section title="Semantic tones">
        <p className={authoringMutedTextClass}>
          Tone is always redundant with a label and an icon, so every state below survives
          greyscale. Violet and cyan identify Scribe and Slate and never appear here.
        </p>
        <div className="flex flex-wrap gap-2">
          {AUTHORING_TONES.map((tone) => (
            <AuthoringToneBadge
              key={tone}
              label={tone}
              tone={tone}
              icon="Circle"
              description={`Semantic ${tone} tone.`}
            />
          ))}
        </div>
      </Section>

      <Section title="Release and environment states">
        <div className="flex flex-wrap gap-3">
          {RELEASE_STATUSES.map((status) => (
            <AuthoringReleaseBadge key={status} status={status} releaseId="r-4821" />
          ))}
        </div>
        <div className="flex flex-wrap gap-3">
          <AuthoringEnvironmentBadge environment="preview" />
          <AuthoringEnvironmentBadge environment="production" />
        </div>
        <ul className={authoringMutedTextClass}>
          {RELEASE_STATUSES.map((status) => (
            <li key={status}>
              <strong>{describeAuthoringRelease(status).label}:</strong>{' '}
              {describeAuthoringRelease(status).description}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Proposals">
        <div className="flex flex-wrap gap-2">
          {REFERENCE_PROPOSAL_STATUSES.map((status) => {
            const descriptor = describeAuthoringProposalStatus(status);
            return (
              <AuthoringToneBadge
                key={status}
                label={descriptor.label}
                tone={descriptor.tone}
                icon={descriptor.icon}
                description={descriptor.description}
              />
            );
          })}
        </div>
        <AuthoringProposalCard proposal={REFERENCE_PROPOSAL} onAction={() => undefined} />
        <AuthoringProposalCard proposal={REFERENCE_RISKY_PROPOSAL} onAction={() => undefined} />
        <AuthoringProposalCard
          proposal={{ ...REFERENCE_PROPOSAL, id: 'prop-ro' }}
          onAction={() => undefined}
          readOnly
        />
      </Section>

      <Section title="Checks">
        <AuthoringCheckSummary checks={REFERENCE_PASSING_CHECKS} title="All passing" />
        <AuthoringCheckSummary checks={REFERENCE_CHECKS} title="Mixed, still running" />
        <AuthoringCheckSummary checks={REFERENCE_BLOCKING_CHECKS} title="Blocked" />
        <AuthoringCheckSummary checks={[]} title="No checks configured" />
      </Section>

      <Section title="Build progress">
        <AuthoringProgressPhases phases={REFERENCE_PHASES} title="Building" />
        <AuthoringProgressPhases phases={REFERENCE_FAILED_PHASES} title="Failed build" />
      </Section>

      <Section title="Split workspace, tree and peek drawer">
        <AuthoringSelectionBar
          selectedCount={selectedCount}
          totalCount={24}
          noun="target"
          actions={REFERENCE_BULK_ACTIONS}
          onAction={() => undefined}
          onClear={() => setSelectedCount(0)}
        />

        <div className="h-96">
          <AuthoringSplitWorkspace
            navigation={{
              title: 'Content',
              children: (
                <AuthoringContentTree
                  nodes={REFERENCE_TREE}
                  label="Reference content"
                  selectedId={selectedNode}
                  expandedIds={expanded}
                  onExpandedChange={setExpanded}
                  onSelect={setSelectedNode}
                />
              ),
            }}
            main={{
              title: 'Editor',
              children: (
                <p className={authoringMutedTextClass}>
                  The focused pane. Selected: {selectedNode}. UXE-2.2 puts the Scribe editor here
                  and UXE-2.3 puts Slate&apos;s sandboxed canvas here.
                </p>
              ),
            }}
            inspector={{
              title: 'Inspector',
              children: <AuthoringCheckSummary checks={REFERENCE_PASSING_CHECKS} collapsed />,
            }}
            onInspectorOpen={() => setDrawerOpen(true)}
          />
        </div>

        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          className="min-h-9 self-start rounded-lg border border-gray-300 px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:border-gray-600"
        >
          Open peek drawer
        </button>

        <AuthoringPeekDrawer
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          title="Release r-4821"
          description="Inspecting without leaving the list. Scroll position and filters are kept."
        >
          <AuthoringCheckSummary checks={REFERENCE_CHECKS} />
        </AuthoringPeekDrawer>
      </Section>

      <Section title="Diff">
        <AuthoringDiffView
          title="Description"
          before={REFERENCE_DIFF.before}
          after={REFERENCE_DIFF.after}
          beforeLabel="Production"
          afterLabel="Draft"
        />
        <AuthoringDiffView title="Unchanged content" before="Same text." after="Same text." />
      </Section>

      <Section title="Impact sheets">
        <p className={authoringMutedTextClass}>
          Publish and rollback confirmations state what changes, show their checks, and disable
          confirmation with a stated reason rather than a generic prompt.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setPromoteOpen(true)}
            className="min-h-9 rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500"
          >
            Promote to production
          </button>
          <button
            type="button"
            onClick={() => setPurgeOpen(true)}
            className="min-h-9 rounded-lg border border-gray-300 px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:border-gray-600"
          >
            Purge cache (irreversible)
          </button>
        </div>

        <AuthoringImpactSheet
          open={promoteOpen}
          onOpenChange={setPromoteOpen}
          sheet={REFERENCE_PROMOTE_SHEET}
          onConfirm={() => setPromoteOpen(false)}
        />
        <AuthoringImpactSheet
          open={purgeOpen}
          onOpenChange={setPurgeOpen}
          sheet={REFERENCE_PURGE_SHEET}
          onConfirm={() => setPurgeOpen(false)}
        />
      </Section>

      <Section title="Analytics states">
        <AuthoringAnalyticsPanel title="Page views" state="ready" series={REFERENCE_SERIES} />
        <AuthoringAnalyticsPanel title="Loading" state="loading" />
        <AuthoringAnalyticsPanel title="No data" state="empty" />
        <AuthoringAnalyticsPanel
          title="Page feedback"
          state="threshold"
          series={REFERENCE_SPARSE_SERIES}
        />
        <AuthoringAnalyticsPanel title="Failed" state="error" onRetry={() => undefined} />
      </Section>
    </div>
  );
}

/**
 * One titled gallery section.
 *
 * @param props - Section heading and its contents.
 */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const headingId = React.useId();

  return (
    <section
      className={`${authoringSurfaceClass} flex flex-col gap-4 p-4`}
      aria-labelledby={headingId}
    >
      <h2 id={headingId} className={authoringSectionTitleClass}>
        {title}
      </h2>
      {children}
    </section>
  );
}

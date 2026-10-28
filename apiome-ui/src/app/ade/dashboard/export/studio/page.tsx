'use client';

import { Suspense, useMemo } from 'react';
import { useAuthSession } from '@lib/auth/session-client';
import { useSearchParams } from 'next/navigation';
import { LoadingState } from '../../../../components/ui/LoadingState';
import { ExportStudio } from '../../../../components/ade/dashboard/export/ExportStudio';
import { ExportStudioSteps } from '../../../../components/ade/dashboard/export/ExportStudioSteps';
import { ExportSourcePicker } from '../../../../components/ade/export-studio/ExportSourcePicker';
import type { ExportedArtifactSummary } from '../../../../components/ade/dashboard/export/ExportDialog';
import { recordRecentExport } from '../../../../components/ade/dashboard/export/recentExports';
import { parseExportStudioUrlState } from '../../../../components/ade/dashboard/export/exportStudioUrlState';
import {
  ExportStudioTabs,
  exportStudioTabFromParams,
} from '../../../../components/ade/export-studio';
import PageHeader from '../../../../components/shell/PageHeader';
import { Page, PageBody } from '../../../../components/shell/pageChrome';
import UnreleasedFeatureGate from '../../../../components/shell/UnreleasedFeatureGate';
import SdkSettingsClient from '../../sdk-settings/SdkSettingsClient';

/**
 * Export Studio route — `…/ade/dashboard/export/studio` (MFX-41.1, #4348).
 *
 * A tenant-scoped, source-scoped workspace: the full-page twin of the ExportDialog. It reads its
 * scope from the query string (the deep-link contract in `exportStudioLink.ts`, validated by
 * `exportStudioUrlState.ts`) and is never a bare global screen — without a source it shows how to
 * open the Studio from a version or catalog item instead.
 *
 * The link carries the whole session (MFX-41.4): source, target, non-default options, and the step
 * to resume on. Every param is validated before the Studio sees it, and whatever cannot be honoured
 * (unreadable options, credential-shaped keys, an unknown target) arrives as a notice the Studio
 * renders instead of failing.
 *
 * ### Two tabs (HIVE-12.2, #5609)
 *
 * `?tab=sdk` selects **SDK & branding** — the SDK settings screen, which left the rail for here
 * because both decide how a version leaves the platform (`/ade/dashboard/sdk-settings` redirects
 * to it). That tab needs no source, so it renders before the source check; it keeps its own
 * release gate. Every header on this route draws the same {@link ExportStudioTabs} strip.
 */
function ExportStudioRouteContent() {
  const { data: session, status } = useAuthSession();
  const searchParams = useSearchParams();

  // Validate the whole link once per query string: scalars, the compact option overrides
  // (MFX-41.3/41.4), and the resumable step, plus the notices for anything that had to degrade.
  const { state, issues } = useMemo(
    () => parseExportStudioUrlState(searchParams),
    [searchParams],
  );
  const { artifact, version, label, target, origin, sourceFormat, options, step } = state;

  if (status === 'loading') {
    return (
      <main className="p-6">
        <LoadingState minHeightClassName="min-h-[220px]" message="Loading Export Studio…" />
      </main>
    );
  }

  if (!session) {
    return (
      <main className="p-6">
        <p className="text-slate-600 dark:text-slate-400">Sign in to use the Export Studio.</p>
      </main>
    );
  }

  const tabs = <ExportStudioTabs />;

  if (exportStudioTabFromParams(searchParams) === 'sdk') {
    return (
      <UnreleasedFeatureGate feature="sdk-settings">
        <SdkSettingsClient tabs={tabs} />
      </UnreleasedFeatureGate>
    );
  }

  // The Studio always exports a source. Without an `artifact` (the rail, the command palette) the
  // Source step is a picker (E1-2): choosing a catalog item or a project version writes the
  // scoped deep link and continues at Target. It still draws the standard header, so the SDK &
  // branding tab is one click away from here.
  if (!artifact) {
    return (
      <Page data-testid="export-studio-unscoped">
        <PageHeader
          breadcrumb={[
            { label: 'Home', href: '/ade/dashboard' },
            { label: 'Ship' },
            { label: 'Export studio' },
          ]}
          title="Export studio"
          tabs={tabs}
        />
        <PageBody>
          {/* E1-2 (#6218): no source yet — the Source step is a picker. Choosing writes the
              resumable deep link and the studio continues at Target. */}
          <ExportStudioSteps stepIndex={0} />
          <div className="xstd-panel" role="group" aria-label="Step 1 of 5: Source" data-testid="export-studio-body">
            <ExportSourcePicker />
          </div>
        </PageBody>
      </Page>
    );
  }

  return (
    <ExportStudio
      artifact={artifact}
      artifactLabel={label}
      version={version}
      initialTarget={target}
      initialOptions={options}
      initialStep={step}
      linkIssues={issues}
      origin={origin}
      sourceFormat={sourceFormat}
      // Record every Studio generate in the MFX-6.5 recent-exports store, keyed by the scoped
      // source — so a catalog item's exports (MFX-41.2) are tracked just as the dialog tracked them.
      onGenerated={(summary: ExportedArtifactSummary) =>
        recordRecentExport(artifact, version || null, summary)
      }
      tabs={tabs}
    />
  );
}

export default function ExportStudioPage() {
  // `useSearchParams` needs a Suspense boundary during Next.js static export.
  return (
    <Suspense
      fallback={
        <main className="p-6">
          <LoadingState minHeightClassName="min-h-[220px]" message="Loading Export Studio…" />
        </main>
      }
    >
      <ExportStudioRouteContent />
    </Suspense>
  );
}

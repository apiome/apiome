'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Download, FileClock, Layers, Loader2, RotateCcw, Send, Shuffle } from 'lucide-react';
import { Alert } from '../../../ui/Alert';
import { Badge } from '../../../ui/Badge';
import { Button } from '../../../ui/Button';
import { VERSION_DIALOG_COPY } from '../../version-dialogs/versionDialogsModel';
import { useExportTargets } from './useExportTargets';
import {
  exportTargetCards,
  fidelityPreSummary,
  tierTone,
  type ExportTargetCard,
} from './exportTargetCatalog';
import { fidelityBadgeLabel, loadRecentExports, type RecentExport } from './recentExports';
import { exportStudioHref } from './exportStudioLink';
import { formatRelativeTime } from '../../../../ade/dashboard/versions/version-history-dag';
import { fetchMyPermissions } from '../../../../ade/dashboard/style-guides/api';
import { MultiTargetChecklist } from './MultiTargetChecklist';
import { MultiExportRun } from './MultiExportRun';
import { allVersionsJobBody } from './exportBatchJob';
import { AutoExportPanel } from '../../export-studio/presets/AutoExportPanel';

interface VersionExportPanelProps {
  /** The artifact (project) id the viewed version belongs to. */
  artifact: string;
  /** The viewed revision (UUID or version label); the latest revision when null. */
  version: string | null;
  /** Human name of the source, carried into the Studio header (falls back to the id). */
  artifactLabel?: string | null;
  /** Only fetch fidelity data while truthy (i.e. while the version view is showing). */
  active: boolean;
  /** Bump to re-read the recent-exports list after an export was recorded. */
  refreshToken?: number;
}

/**
 * VersionExportPanel — the version-scoped export entry point (MFX-6.5 #3859, MFX-41.3 #4350).
 *
 * Rendered on the version view (never in the global nav — a tenant may have hundreds of
 * projects/versions, so export is an action on the version being viewed). Two cards per the
 * export mockup:
 *
 *  - **Convert to any format** — the fidelity pre-summary: which targets carry *this* source
 *    at best fidelity vs lossily (from `GET /api/export/targets`, MFX-2.5 tiers). Every target
 *    chip deep-links into the Export Studio with that target pre-selected, and "Export this
 *    version" opens the Studio unscoped-to-a-target (the compact row-menu action keeps the quick
 *    ExportDialog, MFX-41.3).
 *  - **Recent exports** — this version's past exports with their fidelity % and relative time
 *    (browser-local, recorded when an export emits; see `recentExports.ts`). Each row offers
 *    *re-run in Studio*, reopening the Studio with that run's target and options pre-filled.
 *
 * MFX-39.5 (#4337) adds the project-level surfaces of MFX-EPIC-39 beside them:
 *
 *  - **Export all versions…** (in the first card) — the project-level batch (MFX-39.2): tick one or
 *    more targets, each with this version's fidelity badge, and one job exports every version of the
 *    project to them, as one archive with a folder per version × target.
 *  - **Auto-export on publish** — the export presets every publish of this project runs (MFX-39.4),
 *    with their recent runs, managed here next to the recent exports.
 */
export function VersionExportPanel({
  artifact,
  version,
  artifactLabel,
  active,
  refreshToken = 0,
}: VersionExportPanelProps) {
  const { response, loading, error } = useExportTargets(active, artifact, version);
  const cards = useMemo(() => exportTargetCards(response), [response]);
  const { best, lossy } = useMemo(() => fidelityPreSummary(cards), [cards]);

  // refreshToken is a deliberate extra dependency: the parent bumps it after recording an
  // export so the list re-reads storage without the panel remounting.
  const recent = useMemo(
    () => (active ? loadRecentExports(artifact, version) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [active, artifact, version, refreshToken],
  );

  // MFX-39.5: the all-versions batch picker, and whether the viewer may manage auto-exports.
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchKeys, setBatchKeys] = useState<string[]>([]);
  const [canEdit, setCanEdit] = useState(false);
  useEffect(() => {
    if (!active) return undefined;
    let live = true;
    void fetchMyPermissions().then((perms) => {
      if (!live) return;
      setCanEdit(
        perms?.is_admin === true ||
          (Array.isArray(perms?.permissions) && perms.permissions.includes('projects:edit')),
      );
    });
    return () => {
      live = false;
    };
  }, [active]);
  const toggleBatchKey = useCallback(
    (key: string) => setBatchKeys((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key])),
    [],
  );
  const batchBody = useMemo(() => allVersionsJobBody(artifact, batchKeys), [artifact, batchKeys]);
  const targetLabels = useMemo(
    () => Object.fromEntries(cards.map((card) => [card.key, card.entry.descriptor.label])),
    [cards],
  );

  // The Studio deep link for this version, with no target pre-selected — the "Export this version"
  // call to action. Each target chip and recent-export row builds its own targeted variant.
  const studioHref = useMemo(
    () =>
      exportStudioHref({
        artifact,
        version,
        label: artifactLabel,
        origin: 'versions',
      }),
    [artifact, version, artifactLabel],
  );

  return (
    <div className="vdlg-export" data-testid="version-export-panel">
      <div className="vdlg-export__card">
        <div className="vdlg-caps vdlg-export__card-title">
          <Shuffle aria-hidden />
          Convert to any format
        </div>
        <p className="vdlg-quiet">
          This version is held in the normalized model, so it can be transcoded to any target
          format. Fidelity varies — less-expressive targets drop or approximate detail. Pick a
          target to open it in the Export Studio.
        </p>

        {error && <Alert variant="danger">{error}</Alert>}
        {loading && !error && (
          <div className="vdlg-loading-row" role="status">
            <Loader2 className="animate-spin" aria-hidden />
            {VERSION_DIALOG_COPY.exportMeasuring}
          </div>
        )}
        {!loading && !error && response && (
          <dl className="vdlg-export__summary" data-testid="version-export-presummary">
            <TargetBadgeRow
              label="Best-fidelity targets"
              cards={best}
              artifact={artifact}
              version={version}
              artifactLabel={artifactLabel}
            />
            <TargetBadgeRow
              label="Lossy targets"
              cards={lossy}
              artifact={artifact}
              version={version}
              artifactLabel={artifactLabel}
            />
          </dl>
        )}

        <div className="vdlg-export__cta">
          <Button
            variant="outline"
            onClick={() => setBatchOpen((open) => !open)}
            aria-expanded={batchOpen}
            data-testid="version-export-all-versions"
          >
            <Layers aria-hidden />
            Export all versions…
          </Button>
          <Button asChild>
            <Link href={studioHref} data-testid="version-export-open-studio">
              <Download aria-hidden />
              Export this version
            </Link>
          </Button>
        </div>

        {batchOpen && (
          <div className="vdlg-export__batch" data-testid="version-export-batch">
            <MultiTargetChecklist
              cards={cards}
              selected={batchKeys}
              onToggle={toggleBatchKey}
              minimum={1}
              heading="Export every version of this project to"
            />
            {batchKeys.length > 0 ? (
              <MultiExportRun
                mode="generate"
                body={batchBody}
                labels={targetLabels}
                showItem
                archiveName={`${artifactLabel || artifact}-all-versions.zip`}
              />
            ) : null}
          </div>
        )}
      </div>

      <div className="vdlg-export__card">
        <div className="vdlg-caps vdlg-export__card-title">
          <FileClock aria-hidden />
          Recent exports
        </div>
        {recent.length === 0 ? (
          <p className="vdlg-quiet">{VERSION_DIALOG_COPY.exportNoRecent}</p>
        ) : (
          <ul className="vdlg-export__recent" data-testid="version-recent-exports">
            {recent.map((entry) => (
              <li key={`${entry.targetKey}-${entry.exportedAt}`} className="vdlg-export__recent-row">
                <span className="vdlg-export__recent-main">
                  <span className="vdlg-export__recent-name" title={entry.filename}>
                    {entry.targetLabel}
                  </span>
                  <Link
                    href={rerunHref(entry, artifact, version, artifactLabel)}
                    data-testid="version-recent-export-rerun"
                    title={`Re-run this ${entry.targetLabel} export in the Studio with its options pre-filled`}
                    className="vdlg-link"
                  >
                    <RotateCcw aria-hidden />
                    Re-run in Studio
                  </Link>
                </span>
                <span className="vdlg-export__recent-meta">
                  <Badge variant={tierTone(entry.tier)}>{fidelityBadgeLabel(entry)}</Badge>
                  <span className="vdlg-quiet">
                    {formatRelativeTime(new Date(entry.exportedAt).toISOString()) ?? ''}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {active && (
        <div className="vdlg-export__card">
          <div className="vdlg-caps vdlg-export__card-title">
            <Send aria-hidden />
            Auto-export on publish
          </div>
          <AutoExportPanel
            scope={{ kind: 'project', projectId: artifact, projectName: artifactLabel }}
            canEdit={canEdit}
            embedded
          />
        </div>
      )}
    </div>
  );
}

/**
 * The Studio deep link that reproduces a recorded export (MFX-41.3): the same source and target,
 * carrying that run's non-default option overrides so the Studio pre-fills them.
 */
function rerunHref(
  entry: RecentExport,
  artifact: string,
  version: string | null,
  artifactLabel?: string | null,
): string {
  return exportStudioHref({
    artifact,
    version,
    label: artifactLabel,
    target: entry.targetKey,
    options: entry.options,
    origin: 'versions',
  });
}

interface TargetBadgeRowProps {
  /** The pre-summary row label, e.g. `Best-fidelity targets`. */
  label: string;
  /** The targets in this row; an empty row renders a quiet "None". */
  cards: ExportTargetCard[];
  /** The artifact (project) id, for each chip's Studio deep link. */
  artifact: string;
  /** The viewed revision selector, for each chip's Studio deep link. */
  version: string | null;
  /** Human name of the source, carried into the Studio header. */
  artifactLabel?: string | null;
}

/**
 * One pre-summary row: a label plus each target as a tier-colored chip that deep-links into the
 * Export Studio with that target pre-selected (MFX-41.3).
 */
function TargetBadgeRow({ label, cards, artifact, version, artifactLabel }: TargetBadgeRowProps) {
  return (
    <div className="vdlg-export__summary-row">
      <dt className="vdlg-caps">{label}</dt>
      <dd className="vdlg-chips">
        {cards.length === 0 ? (
          <span className="vdlg-quiet">{VERSION_DIALOG_COPY.exportBucketEmpty}</span>
        ) : (
          cards.map((card) => (
            <Link
              key={card.key}
              href={exportStudioHref({
                artifact,
                version,
                label: artifactLabel,
                target: card.key,
                origin: 'versions',
              })}
              data-testid="version-export-target-chip"
              title={`Export to ${card.entry.descriptor.label} — ${card.entry.fidelity.preserved_percent}% preserved`}
              className="vdlg-export__chip"
            >
              <Badge variant={tierTone(card.entry.fidelity.tier)}>
                {card.entry.descriptor.label}
              </Badge>
            </Link>
          ))
        )}
      </dd>
    </div>
  );
}

export default VersionExportPanel;

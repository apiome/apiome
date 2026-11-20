'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState, type ChangeEvent } from 'react';
import Link from 'next/link';
import { Eye, FileOutput, GitBranchPlus, Layers, Lock, Pencil, Plus, Upload, X } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Label } from '@/app/components/ui/Label';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { OverlayReportPanel } from '@/app/components/ade/dashboard/export/OverlayReportPanel';
import { parseOverlayFile } from '@/app/components/ade/dashboard/export/exportOverlays';
import { exportStudioHref } from '@/app/components/ade/dashboard/export/exportStudioLink';
import { formatVersionWithPrefix } from '@/app/utils/version-display';

import {
  CODE_VERSION_PUBLISHED,
  OVERLAY_SOURCE_LABEL,
  VersionOverlaysError,
  addVersionOverlay,
  fetchVersionOverlayPreview,
  fetchVersionOverlays,
  removeVersionOverlay,
  shortFingerprint,
  type StoredVersionOverlay,
  type VersionOverlayApplyResult,
  type VersionOverlayChain,
  type VersionOverlayPreview,
  type VersionOverlaysRevisionRow,
} from './versionOverlaysApi';
import { OverlayApplyDialog } from './OverlayApplyDialog';
import { OverlayEditorDialog } from './OverlayEditorDialog';
import { OverlayActionsTable, OverlayDiffTable } from './OverlayPreviewTables';

/** One revision the panel can show (the Versions page's rows). */
export type VersionOverlaysRevision = VersionOverlaysRevisionRow;

/** Props for {@link VersionOverlaysPanel}. */
export interface VersionOverlaysPanelProps {
  /** The selected project. */
  projectId: string;
  /** The project's revisions. */
  versions: readonly VersionOverlaysRevision[];
  /** The revision to open first (the page's selected revision), when it is in `versions`. */
  initialRevisionId?: string | null;
  /** Called after **Apply as version** created a new version (the page reloads its list). */
  onVersionCreated?: (result: VersionOverlayApplyResult) => void;
}

/** Which editor is open: a new overlay (`overlay: null`) or a stored one. */
type EditorState = { overlay: StoredVersionOverlay | null; key: number } | null;

/**
 * The Versions screen's **Overlays** tab — GVM-4.3 (#5878); the overlay manager — COA-2.7 (#7050).
 *
 * Shows a revision's stored overlay chain: the Overlay documents applied, in order, when the
 * revision is exported and when it is published. Its stored model and the Studio are never
 * changed. On a draft revision you can write a **New overlay** (or **Edit** a stored one) in the
 * overlay editor, **upload** overlay files and **remove** overlays; a published revision's chain is
 * read-only, and its publish render (the source and resolved fingerprints, side by side) is shown.
 * **Preview** renders the chain exactly as an export does: every action with the number of values
 * its target matched, every changed value before and after with the action that changed it, and the
 * findings. **Apply as version** imports the rendered document as a new version, and **Export with
 * overlays** opens Export Studio on the revision (the chain applies to every export).
 *
 * @param props See {@link VersionOverlaysPanelProps}.
 * @returns The panel.
 */
export function VersionOverlaysPanel({
  projectId,
  versions,
  initialRevisionId,
  onVersionCreated,
}: VersionOverlaysPanelProps) {
  const revisions = useMemo(
    () =>
      versions
        .filter((v) => v.project_id === projectId && !v.deleted_at)
        .sort((a, b) => b.version_id.localeCompare(a.version_id, undefined, { numeric: true })),
    [versions, projectId]
  );
  const [revisionId, setRevisionId] = useState('');
  const [chain, setChain] = useState<VersionOverlayChain | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notices, setNotices] = useState<string[]>([]);
  const [preview, setPreview] = useState<VersionOverlayPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [editor, setEditor] = useState<EditorState>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const inputId = useId();
  const selectId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (revisions.length === 0) {
      setRevisionId('');
      return;
    }
    if (!revisionId || !revisions.some((r) => r.id === revisionId)) {
      const initial = revisions.find((r) => r.id === initialRevisionId);
      setRevisionId((initial ?? revisions[0]).id);
    }
  }, [revisions, revisionId, initialRevisionId]);

  useEffect(() => {
    if (!revisionId) {
      setChain(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setPreview(null);
    fetchVersionOverlays(projectId, revisionId)
      .then((next) => {
        if (cancelled) return;
        setChain(next);
        setError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setChain(null);
        setError(e instanceof Error ? e.message : 'The overlay chain could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, revisionId, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const readOnly = !!chain?.published;
  const full = !!chain && chain.overlays.length >= chain.max_overlays;
  const revision = revisions.find((r) => r.id === revisionId);
  const revisionLabel = revision ? formatVersionWithPrefix(revision.version_id) : '';
  const existingLabels = useMemo(() => revisions.map((r) => r.version_id), [revisions]);
  const fullTitle = chain ? `A revision holds at most ${chain.max_overlays} overlays.` : undefined;

  /** Say why a write was refused, in the words the product uses. */
  const refusal = (e: unknown): string => {
    if (e instanceof VersionOverlaysError && e.code === CODE_VERSION_PUBLISHED) {
      return 'This revision is published, so its overlays are read-only.';
    }
    return e instanceof Error ? e.message : 'The overlay could not be saved.';
  };

  const handleFiles = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? []);
      event.target.value = '';
      if (files.length === 0 || !revisionId) return;
      setBusy(true);
      const problems: string[] = [];
      for (const file of files) {
        const parsed = parseOverlayFile(file.name, await file.text(), file.size);
        if (!parsed.ok) {
          problems.push(parsed.error);
          continue;
        }
        try {
          await addVersionOverlay(projectId, revisionId, {
            name: parsed.overlay.name,
            source: 'manual',
            document: parsed.overlay.document,
          });
        } catch (e) {
          problems.push(`${file.name}: ${refusal(e)}`);
        }
      }
      setNotices(problems);
      setBusy(false);
      reload();
    },
    [projectId, revisionId, reload]
  );

  const handleRemove = useCallback(
    async (overlayId: string, name: string) => {
      setBusy(true);
      try {
        await removeVersionOverlay(projectId, revisionId, overlayId);
        setNotices([]);
      } catch (e) {
        setNotices([`${name}: ${refusal(e)}`]);
      } finally {
        setBusy(false);
        reload();
      }
    },
    [projectId, revisionId, reload]
  );

  const handlePreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      setPreview(await fetchVersionOverlayPreview(projectId, revisionId));
      setNotices([]);
    } catch (e) {
      setPreview(null);
      setNotices([e instanceof Error ? e.message : 'The preview could not be rendered.']);
    } finally {
      setPreviewLoading(false);
    }
  }, [projectId, revisionId]);

  if (revisions.length === 0) {
    return (
      <p className="xstd-empty" data-testid="version-overlays-no-revisions">
        This project has no revisions yet.
      </p>
    );
  }

  return (
    <section className="xstd-stack xstd-panel" data-testid="version-overlays" aria-label="Overlays">
      <div className="xstd-caps">
        <Layers aria-hidden />
        Overlays
      </div>
      <p className="hive-quiet">
        Overlays change what this revision exports and publishes — descriptions, servers,{' '}
        <span className="xstd-mono">x-</span> extensions — without changing the revision itself.
        They apply in the order listed, to revisions imported from OpenAPI. Apply them as a version
        to make the changes part of a new revision.
      </p>

      <div className="xstd-stack xstd-stack--tight">
        <Label htmlFor={selectId}>Revision</Label>
        <select
          id={selectId}
          className="hive-control vovl-select"
          value={revisionId}
          onChange={(event) => setRevisionId(event.target.value)}
          data-testid="version-overlays-revision"
        >
          {revisions.map((r) => (
            <option key={r.id} value={r.id}>
              {formatVersionWithPrefix(r.version_id)}
              {r.published ? ' (published)' : ' (draft)'}
            </option>
          ))}
        </select>
      </div>

      {loading && !chain ? (
        <LoadingState message="Loading overlays…" data-testid="version-overlays-loading" />
      ) : error ? (
        <ErrorState title="Overlays could not be loaded" description={error} onRetry={reload} />
      ) : chain ? (
        <>
          {readOnly ? (
            <p className="xstd-notice" data-tone="accent" data-testid="version-overlays-read-only">
              <Lock aria-hidden />
              <span className="xstd-notice__grow">
                This revision is published, so its overlays are read-only. Change the chain on a
                draft revision.
              </span>
            </p>
          ) : null}

          {chain.overlays.length === 0 ? (
            <p className="xstd-empty" data-testid="version-overlays-empty">
              No overlays — this revision exports and publishes as it is.
            </p>
          ) : (
            <ol className="xstd-overlay__list" aria-label="Overlays, in the order they apply">
              {chain.overlays.map((overlay) => (
                <li
                  key={overlay.id}
                  className="xstd-overlay__row"
                  data-testid={`version-overlay-${overlay.position}`}
                >
                  <span className="xstd-overlay__order" aria-hidden>
                    {overlay.position + 1}
                  </span>
                  <span className="xstd-overlay__main">
                    <span className="xstd-overlay__name">{overlay.name}</span>
                    <span className="hive-quiet">
                      {overlay.action_count} {overlay.action_count === 1 ? 'action' : 'actions'} ·{' '}
                      <span className="xstd-mono">{shortFingerprint(overlay.content_fingerprint)}</span>
                    </span>
                  </span>
                  <Badge variant="outline">{OVERLAY_SOURCE_LABEL[overlay.source] ?? overlay.source}</Badge>
                  {readOnly ? null : (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Edit ${overlay.name}`}
                      title={`Edit ${overlay.name}`}
                      disabled={busy}
                      onClick={() => setEditor({ overlay, key: Date.now() })}
                      data-testid={`version-overlay-edit-${overlay.position}`}
                    >
                      <Pencil aria-hidden />
                    </Button>
                  )}
                  {readOnly ? null : (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove ${overlay.name}`}
                      title={`Remove ${overlay.name}`}
                      disabled={busy}
                      onClick={() => void handleRemove(overlay.id, overlay.name)}
                      data-testid={`version-overlay-remove-${overlay.position}`}
                    >
                      <X aria-hidden />
                    </Button>
                  )}
                </li>
              ))}
            </ol>
          )}

          <div className="vovl-actions">
            {readOnly ? null : (
              <>
                <input
                  ref={inputRef}
                  id={inputId}
                  type="file"
                  accept=".json,.yaml,.yml,application/json,application/yaml"
                  multiple
                  className="sr-only"
                  aria-label="Overlay files"
                  data-testid="version-overlays-input"
                  onChange={(event) => void handleFiles(event)}
                />
                <Button
                  variant="outline"
                  onClick={() => setEditor({ overlay: null, key: Date.now() })}
                  disabled={busy || full}
                  title={full ? fullTitle : busy ? 'Saving the overlay chain…' : undefined}
                  data-testid="version-overlays-new"
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  New overlay
                </Button>
                <Button
                  variant="outline"
                  onClick={() => inputRef.current?.click()}
                  disabled={busy || full}
                  title={full ? fullTitle : busy ? 'Saving the overlay chain…' : undefined}
                  data-testid="version-overlays-add"
                >
                  <Upload className="h-4 w-4" aria-hidden />
                  Upload overlay
                </Button>
              </>
            )}
            {chain.overlays.length > 0 ? (
              <Button
                variant="outline"
                onClick={() => void handlePreview()}
                disabled={previewLoading}
                title={previewLoading ? 'Rendering the preview…' : undefined}
                data-testid="version-overlays-preview"
              >
                <Eye className="h-4 w-4" aria-hidden />
                Preview
              </Button>
            ) : null}
            {chain.overlays.length > 0 ? (
              <Button
                variant="outline"
                onClick={() => setApplyOpen(true)}
                disabled={busy}
                title={busy ? 'Saving the overlay chain…' : undefined}
                data-testid="version-overlays-apply"
              >
                <GitBranchPlus className="h-4 w-4" aria-hidden />
                Apply as version
              </Button>
            ) : null}
            {chain.overlays.length > 0 ? (
              <Button variant="outline" asChild>
                <Link
                  href={exportStudioHref({
                    artifact: projectId,
                    version: revisionId,
                    label: revisionLabel || null,
                    origin: 'versions',
                  })}
                  data-testid="version-overlays-export"
                >
                  <FileOutput className="h-4 w-4" aria-hidden />
                  Export with overlays
                </Link>
              </Button>
            ) : null}
          </div>

          {notices.length > 0 ? (
            <ul className="xstd-overlay__list" role="alert" data-testid="version-overlays-notices">
              {notices.map((message) => (
                <li key={message} className="xstd-notice" data-tone="warn">
                  {message}
                </li>
              ))}
            </ul>
          ) : null}

          {chain.render ? (
            <dl className="xstd-stack xstd-stack--tight" data-testid="version-overlays-render">
              <dt className="xstd-caps">Published render</dt>
              <dd className="hive-quiet">
                Source <span className="xstd-mono">{shortFingerprint(chain.render.source_fingerprint)}</span>{' '}
                → resolved{' '}
                <span className="xstd-mono">{shortFingerprint(chain.render.resolved_fingerprint)}</span>
                {' · '}
                {chain.render.changes} {chain.render.changes === 1 ? 'change' : 'changes'}
                {chain.render.findings.length > 0
                  ? ` · ${chain.render.findings.length} ${chain.render.findings.length === 1 ? 'finding' : 'findings'}`
                  : ''}
              </dd>
            </dl>
          ) : null}

          {preview ? (
            <div className="xstd-stack" data-testid="version-overlays-preview-result">
              <p className="hive-quiet">
                Source <span className="xstd-mono">{shortFingerprint(preview.source_fingerprint)}</span> →
                resolved <span className="xstd-mono">{shortFingerprint(preview.resolved_fingerprint)}</span>
              </p>
              <OverlayActionsTable actions={preview.report?.actions ?? []} />
              {preview.diff ? <OverlayDiffTable rows={preview.diff} /> : null}
              {preview.report ? <OverlayReportPanel report={preview.report} /> : null}
            </div>
          ) : null}
        </>
      ) : null}

      {editor && revisionId ? (
        <OverlayEditorDialog
          key={editor.key}
          open
          onOpenChange={(open) => (open ? undefined : setEditor(null))}
          projectId={projectId}
          revisionId={revisionId}
          overlay={editor.overlay}
          onSaved={() => {
            setNotices([]);
            setPreview(null);
            reload();
          }}
        />
      ) : null}

      {applyOpen && chain && revisionId ? (
        <OverlayApplyDialog
          open
          onOpenChange={setApplyOpen}
          projectId={projectId}
          revisionId={revisionId}
          revisionLabel={revisionLabel}
          overlayCount={chain.overlays.length}
          existingLabels={existingLabels}
          onApplied={(result) => onVersionCreated?.(result)}
        />
      ) : null}
    </section>
  );
}

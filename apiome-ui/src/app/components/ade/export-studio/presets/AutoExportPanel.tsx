'use client';

import { useCallback, useEffect, useState } from 'react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Label } from '@/app/components/ui/Label';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { fetchProjectOptions, type ProjectOption } from '@/app/ade/dashboard/style-guides/api';

import {
  RUN_STATUS_LABELS,
  createAutoExport,
  deleteAutoExport,
  fetchAutoExportRuns,
  fetchAutoExports,
  releaseAutoExportRun,
  runTone,
  subscriptionSummary,
  updateAutoExport,
  type AutoExportRun,
  type AutoExportSubscription,
  type HaltAt,
} from './autoExportApi';
import type { ExportPreset } from './exportPresetsModel';

/** Props for {@link AutoExportPanel}. */
export interface AutoExportPanelProps {
  /** The preset the panel subscribes. */
  preset: ExportPreset;
  /** Whether the viewer may change subscriptions (`projects:edit`; the API also needs `versions:publish`). */
  canEdit: boolean;
}

/**
 * **Auto-export on publish** for one preset, on Export studio's Presets tab (MFX-39.4, #4336).
 *
 * Lists the projects whose every publish runs this preset, each with its halt rule and recent runs; adds a
 * project (**Halt delivery at** `critical` or `warn`, **Deliver even past it**); switches a subscription
 * on or off or removes it; and **Release**s a halted run — delivers it anyway. A preset without a delivery
 * profile still exports on publish, but has nothing to deliver.
 *
 * @param props See {@link AutoExportPanelProps}.
 * @returns The panel.
 */
export function AutoExportPanel({ preset, canEdit }: AutoExportPanelProps) {
  const [subs, setSubs] = useState<AutoExportSubscription[] | null>(null);
  const [runs, setRuns] = useState<Record<string, AutoExportRun[]>>({});
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState('');
  const [haltAt, setHaltAt] = useState<HaltAt>('critical');
  const [approveLoss, setApproveLoss] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await fetchAutoExports(preset.id);
      setSubs(rows);
      const entries = await Promise.all(
        rows.map(async (sub) => [sub.id, await fetchAutoExportRuns(sub.id).catch(() => [])] as const),
      );
      setRuns(Object.fromEntries(entries));
    } catch (cause) {
      setSubs([]);
      setError(cause instanceof Error ? cause.message : 'Could not load the auto-exports');
    }
  }, [preset.id]);

  useEffect(() => {
    void load();
    void fetchProjectOptions().then(setProjects).catch(() => setProjects([]));
  }, [load]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The change failed');
    } finally {
      setBusy(false);
    }
  };

  const subscribed = new Set((subs ?? []).map((sub) => sub.projectId));

  return (
    <section className="xdlv-job" aria-label={`Auto-export ${preset.name} on publish`} data-testid="auto-export-panel">
      <div className="xdlv-job__head">
        <h3 className="xdlv-job__title">Auto-export on publish</h3>
      </div>
      <p className="xdlv-quiet">
        Every publish of these projects runs <strong>{preset.name}</strong> and delivers it
        {preset.deliveryProfileName ? ` with ${preset.deliveryProfileName}` : ' (no delivery profile: export only)'} —
        unless the export loses too much.
      </p>
      {error ? <p className="xdlv-job__error" role="alert">{error}</p> : null}

      {subs === null ? (
        <Skeleton className="xdlv-skeleton" />
      ) : subs.length === 0 ? (
        <p className="xdlv-quiet">No project runs this preset on publish yet.</p>
      ) : (
        <ul className="xdlv-attempts">
          {subs.map((sub) => (
            <li key={sub.id} className="xdlv-attempt" data-testid="auto-export-subscription">
              <div className="xdlv-attempt__head">
                <span className="xdlv-profile__name">{sub.projectName ?? sub.projectId}</span>
                <span className="xdlv-attempt__channel">{subscriptionSummary(sub)}</span>
              </div>
              {canEdit ? (
                <div className="xdlv-profile__actions">
                  <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() => void act(() => updateAutoExport(sub.id, { active: !sub.active }))}>
                    {sub.active ? 'Turn off' : 'Turn on'}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() => void act(() => deleteAutoExport(sub.id))}>
                    Remove
                  </Button>
                </div>
              ) : null}
              <ul className="xdlv-attempts" aria-label={`Recent auto-exports of ${sub.projectName ?? sub.projectId}`}>
                {(runs[sub.id] ?? []).map((run) => (
                  <li key={run.id} className="xdlv-attempt__meta" data-testid="auto-export-run">
                    <Badge variant={runTone(run.status)}>{RUN_STATUS_LABELS[run.status]}</Badge>
                    {run.createdAt ? <time dateTime={run.createdAt}>{new Date(run.createdAt).toLocaleString()}</time> : null}
                    {run.lossSeverity ? <span>Loss: {run.lossSeverity}</span> : null}
                    {run.lossReasons[0] ? <span>{run.lossReasons[0]}</span> : null}
                    {run.errorCode ? <code className="mono">{run.errorCode}</code> : null}
                    {run.status === 'halted' && canEdit ? (
                      <Button size="sm" variant="outline" disabled={busy}
                        onClick={() => void act(() => releaseAutoExportRun(run.id))}>
                        Release
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      {canEdit ? (
        <div className="xdlv-form" data-testid="auto-export-add">
          <div className="xdlv-field">
            <Label htmlFor="xauto-project">Project</Label>
            <select id="xauto-project" className="hive-control xdlv-select" value={projectId}
              onChange={(event) => setProjectId(event.target.value)}>
              <option value="">Choose a project…</option>
              {projects.filter((p) => !subscribed.has(p.id)).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xauto-halt">Halt delivery at</Label>
            <select id="xauto-halt" className="hive-control xdlv-select" value={haltAt}
              onChange={(event) => setHaltAt(event.target.value === 'warn' ? 'warn' : 'critical')}>
              <option value="critical">Critical loss</option>
              <option value="warn">Any loss</option>
            </select>
          </div>
          <p className="xdlv-hint">
            Critical: a severe or near-empty conversion, a types-only result, or a critical construct lost.
          </p>
          <label className="xdlv-choice">
            <input type="checkbox" checked={approveLoss} onChange={(event) => setApproveLoss(event.target.checked)} />
            <span className="xdlv-choice__name">Deliver even past it</span>
            <span className="xdlv-choice__meta">Pre-approve the loss; recorded on every run.</span>
          </label>
          <div className="xdlv-form__actions">
            <Button size="sm" disabled={!projectId || busy} data-testid="auto-export-add-button"
              onClick={() => void act(async () => {
                await createAutoExport({ projectId, preset: preset.id, haltAt, approveLoss });
                setProjectId('');
                setApproveLoss(false);
              })}>
              Run on every publish
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

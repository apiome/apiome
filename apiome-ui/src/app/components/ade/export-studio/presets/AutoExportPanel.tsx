'use client';

import { useCallback, useEffect, useState } from 'react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Label } from '@/app/components/ui/Label';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { fetchProjectOptions } from '@/app/ade/dashboard/style-guides/api';

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
import { fetchExportPresets } from './exportPresetsApi';
import { presetProfileNames, type ExportPreset } from './exportPresetsModel';

/** What the panel is about: one preset's projects, or one project's presets. */
export type AutoExportScope =
  | { kind: 'preset'; preset: ExportPreset }
  | { kind: 'project'; projectId: string; projectName?: string | null };

/** Props for {@link AutoExportPanel}. */
export interface AutoExportPanelProps {
  /** A preset (Export studio's Presets tab) or a project (the version view, MFX-39.5). */
  scope: AutoExportScope;
  /** Whether the viewer may change subscriptions (`projects:edit`; the API also needs `versions:publish`). */
  canEdit: boolean;
  /** Drawn inside another card that carries the title (the version view): no box, no heading of its own. */
  embedded?: boolean;
}

/** One choice of the add form: a project (preset scope) or a preset (project scope). */
interface Choice {
  id: string;
  name: string;
}

/**
 * **Auto-export on publish** (MFX-39.4, #4336; on the version view, MFX-39.5, #4337).
 *
 * Lists the subscriptions in scope — the projects whose every publish runs a preset, or the presets every
 * publish of a project runs — each with its halt rule and recent runs. Adds one (**Halt delivery at**
 * `critical` or `warn`, **Deliver even past it**), switches one on or off or removes it, and **Release**s a
 * halted run — delivers it anyway.
 *
 * @param props See {@link AutoExportPanelProps}.
 * @returns The panel.
 */
export function AutoExportPanel({ scope, canEdit, embedded = false }: AutoExportPanelProps) {
  const [subs, setSubs] = useState<AutoExportSubscription[] | null>(null);
  const [runs, setRuns] = useState<Record<string, AutoExportRun[]>>({});
  const [choices, setChoices] = useState<Choice[]>([]);
  const [chosen, setChosen] = useState('');
  const [haltAt, setHaltAt] = useState<HaltAt>('critical');
  const [approveLoss, setApproveLoss] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const byPreset = scope.kind === 'preset';
  const scopeKey = byPreset ? scope.preset.id : scope.projectId;

  const load = useCallback(async () => {
    try {
      const rows = await fetchAutoExports(byPreset ? { preset: scopeKey } : { projectId: scopeKey });
      setSubs(rows);
      const entries = await Promise.all(
        rows.map(async (sub) => [sub.id, await fetchAutoExportRuns(sub.id).catch(() => [])] as const),
      );
      setRuns(Object.fromEntries(entries));
    } catch (cause) {
      setSubs([]);
      setError(cause instanceof Error ? cause.message : 'Could not load the auto-exports');
    }
  }, [byPreset, scopeKey]);

  useEffect(() => {
    void load();
    const options: Promise<Choice[]> = byPreset
      ? fetchProjectOptions()
      : fetchExportPresets().then((presets) => presets.map((p) => ({ id: p.id, name: p.name })));
    void options.then(setChoices).catch(() => setChoices([]));
  }, [load, byPreset]);

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

  const taken = new Set((subs ?? []).map((sub) => (byPreset ? sub.projectId : sub.presetId)));
  const rowName = (sub: AutoExportSubscription) =>
    byPreset ? (sub.projectName ?? sub.projectId) : (sub.presetName ?? sub.presetId);
  const title = byPreset ? `Auto-export ${scope.preset.name} on publish` : 'Auto-export on publish';

  return (
    <section className={embedded ? 'xdlv-embedded' : 'xdlv-job'} aria-label={title} data-testid="auto-export-panel">
      {embedded ? null : (
        <div className="xdlv-job__head">
          <h3 className="xdlv-job__title">Auto-export on publish</h3>
        </div>
      )}
      <p className="xdlv-quiet">
        {byPreset ? (
          <>
            Every publish of these projects runs <strong>{scope.preset.name}</strong> and delivers it
            {presetProfileNames(scope.preset).length
              ? ` with ${presetProfileNames(scope.preset).join(', ')}`
              : ' (no delivery profile: export only)'}{' '}
            — unless the export loses too much.
          </>
        ) : (
          <>Every publish of this project runs these export presets and delivers them — unless the export loses too much.</>
        )}
      </p>
      {error ? <p className="xdlv-job__error" role="alert">{error}</p> : null}

      {subs === null ? (
        <Skeleton className="xdlv-skeleton" />
      ) : subs.length === 0 ? (
        <p className="xdlv-quiet">
          {byPreset ? 'No project runs this preset on publish yet.' : 'No export preset runs on publish of this project yet.'}
        </p>
      ) : (
        <ul className="xdlv-attempts">
          {subs.map((sub) => (
            <li key={sub.id} className="xdlv-attempt" data-testid="auto-export-subscription">
              <div className="xdlv-attempt__head">
                <span className="xdlv-profile__name">{rowName(sub)}</span>
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
              <ul className="xdlv-attempts" aria-label={`Recent auto-exports of ${rowName(sub)}`}>
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
            <Label htmlFor={`xauto-choice-${scopeKey}`}>{byPreset ? 'Project' : 'Export preset'}</Label>
            <select id={`xauto-choice-${scopeKey}`} className="hive-control xdlv-select" value={chosen}
              onChange={(event) => setChosen(event.target.value)}>
              <option value="">{byPreset ? 'Choose a project…' : 'Choose a preset…'}</option>
              {choices.filter((c) => !taken.has(c.id)).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {!byPreset && choices.length === 0 ? (
              <p className="xdlv-hint">No export presets yet. Save one with Save as preset in Export studio.</p>
            ) : null}
          </div>
          <div className="xdlv-field">
            <Label htmlFor={`xauto-halt-${scopeKey}`}>Halt delivery at</Label>
            <select id={`xauto-halt-${scopeKey}`} className="hive-control xdlv-select" value={haltAt}
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
            <Button size="sm" disabled={!chosen || busy} data-testid="auto-export-add-button"
              onClick={() => void act(async () => {
                await createAutoExport({
                  projectId: byPreset ? chosen : scope.projectId,
                  preset: byPreset ? scope.preset.id : chosen,
                  haltAt,
                  approveLoss,
                });
                setChosen('');
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

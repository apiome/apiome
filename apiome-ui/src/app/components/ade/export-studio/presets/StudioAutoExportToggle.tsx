'use client';

import { useCallback, useEffect, useState } from 'react';
import { Zap } from 'lucide-react';

import {
  createAutoExport,
  deleteAutoExport,
  fetchAutoExports,
  subscriptionSummary,
  type AutoExportSubscription,
} from './autoExportApi';
import type { ExportPreset } from './exportPresetsModel';

/** Props for {@link StudioAutoExportToggle}. */
export interface StudioAutoExportToggleProps {
  /** The project being exported — every publish of it runs the preset. */
  projectId: string;
  /**
   * The preset in play: the one just saved, or the one applied and not changed since. Null when the
   * selection is not a saved preset.
   */
  preset: ExportPreset | null;
  /** The Presets tab, where the halt rule and the other projects are managed. */
  presetsHref: string;
}

/**
 * **Auto-export on publish** on Export studio's Review step (MFX-46.4, #4382).
 *
 * The Studio feeds the auto-export subscriptions of MFX-39.4 rather than duplicating them: with a preset
 * in play, one checkbox subscribes this project to it (halting delivery at critical loss, loss not
 * pre-approved) or removes the subscription; the halt rule, the runs and the other projects stay on the
 * **Presets** tab. Without a preset in play it says to save the selection as a preset first.
 *
 * @param props See {@link StudioAutoExportToggleProps}.
 * @returns The toggle.
 */
export function StudioAutoExportToggle({ projectId, preset, presetsHref }: StudioAutoExportToggleProps) {
  // The subscription of this project to the preset, keyed by `projectId:presetId` so a new preset or
  // project starts from "not loaded" without resetting state in an effect.
  const scopeKey = preset ? `${projectId}:${preset.id}` : null;
  const [loaded, setLoaded] = useState<{ key: string; sub: AutoExportSubscription | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (key: string, presetId: string) => {
    try {
      const rows = await fetchAutoExports({ projectId });
      setLoaded({ key, sub: rows.find((row) => row.presetId === presetId) ?? null });
    } catch (cause) {
      setLoaded({ key, sub: null });
      setError(cause instanceof Error ? cause.message : 'Could not load the auto-exports');
    }
  }, [projectId]);

  useEffect(() => {
    if (scopeKey && preset) void load(scopeKey, preset.id);
  }, [scopeKey, preset, load]);

  if (!preset || !scopeKey) {
    return (
      <section className="xdlv-job" aria-label="Auto-export on publish" data-testid="studio-auto-export">
        <div className="xdlv-job__head">
          <Zap aria-hidden />
          <h3 className="xdlv-job__title">Auto-export on publish</h3>
        </div>
        <p className="xdlv-quiet" data-testid="studio-auto-export-needs-preset">
          Save these settings as a preset to run them on every publish of this project.
        </p>
      </section>
    );
  }

  const current = loaded?.key === scopeKey ? loaded : null;
  const sub = current?.sub ?? null;

  const toggle = async (on: boolean) => {
    setBusy(true);
    setError(null);
    try {
      if (on) await createAutoExport({ projectId, preset: preset.id, haltAt: 'critical', approveLoss: false });
      else if (sub) await deleteAutoExport(sub.id);
      await load(scopeKey, preset.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The change failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="xdlv-job" aria-label="Auto-export on publish" data-testid="studio-auto-export">
      <div className="xdlv-job__head">
        <Zap aria-hidden />
        <h3 className="xdlv-job__title">Auto-export on publish</h3>
        <a className="xdlv-job__manage" href={presetsHref}>
          Manage on Presets
        </a>
      </div>
      <label className="xdlv-choice">
        <input
          type="checkbox"
          data-testid="studio-auto-export-toggle"
          checked={sub !== null}
          disabled={current === null || busy}
          onChange={(event) => void toggle(event.target.checked)}
        />
        <span className="xdlv-choice__name">
          Run <strong>{preset.name}</strong> on every publish of this project
        </span>
        <span className="xdlv-choice__meta">
          {sub ? subscriptionSummary(sub) : 'Halts delivery at critical loss'}
        </span>
      </label>
      {error ? (
        <p className="xdlv-job__error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

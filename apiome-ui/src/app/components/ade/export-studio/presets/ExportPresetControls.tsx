'use client';

import { useEffect, useState } from 'react';
import { Bookmark } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';

import { ExportPresetsError, createExportPreset, fetchExportPresets } from './exportPresetsApi';
import { presetBody, targetsSummary, type ExportPreset, type PresetTarget } from './exportPresetsModel';

/** Props for {@link ExportPresetPicker}. */
export interface ExportPresetPickerProps {
  /** Apply the chosen preset to the studio. */
  onApply: (preset: ExportPreset) => void;
  /** Set after an apply: what could not be applied, or what was. */
  notice?: string | null;
  /** The Presets tab, for the "manage" link. */
  manageHref: string;
}

/**
 * **Apply a preset** on Export studio's Target step (MFX-39.3, #4335).
 *
 * Lists the workspace's presets; **Apply** selects the preset's target (with its options) — or ticks its
 * targets under **Several targets** — and ticks its delivery profile on Review. Renders nothing while the
 * presets load, and a pointer to **Save as preset** when there are none.
 *
 * @param props See {@link ExportPresetPickerProps}.
 * @returns The picker.
 */
export function ExportPresetPicker({ onApply, notice, manageHref }: ExportPresetPickerProps) {
  const [presets, setPresets] = useState<ExportPreset[] | null>(null);
  const [chosen, setChosen] = useState('');

  useEffect(() => {
    let live = true;
    fetchExportPresets()
      .then((rows) => live && setPresets(rows))
      .catch(() => live && setPresets([]));
    return () => {
      live = false;
    };
  }, []);

  if (presets === null || presets.length === 0) return null;
  const preset = presets.find((p) => p.id === chosen) ?? null;

  return (
    <section className="xdlv-job" aria-label="Apply a preset" data-testid="export-preset-picker">
      <div className="xdlv-job__head">
        <Bookmark aria-hidden />
        <h3 className="xdlv-job__title">Apply a preset</h3>
        <a className="xdlv-job__manage" href={manageHref}>
          Manage presets
        </a>
      </div>
      <div className="xdlv-job__now">
        <Label htmlFor="xprs-apply" className="sr-only">
          Export preset
        </Label>
        <select id="xprs-apply" className="hive-control xdlv-select" value={chosen}
          onChange={(event) => setChosen(event.target.value)}>
          <option value="">Choose a preset…</option>
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <Button size="sm" variant="outline" disabled={!preset} onClick={() => preset && onApply(preset)}>
          Apply
        </Button>
      </div>
      {preset ? (
        <p className="xdlv-quiet">
          <span className="mono">{targetsSummary(preset.targets)}</span>
          {preset.deliveryProfileName ? ` · delivered with ${preset.deliveryProfileName}` : ''}
        </p>
      ) : null}
      {notice ? <p className="xdlv-quiet" role="status">{notice}</p> : null}
    </section>
  );
}

/** Props for {@link SavePresetForm}. */
export interface SavePresetFormProps {
  /** The targets the studio would export, in order, each with its changed options. */
  targets: PresetTarget[];
  /** The delivery profile ticked on Review (the first, when several), or null. */
  deliveryProfileId: string | null;
}

/**
 * **Save as preset** on Export studio's Review step (MFX-39.3, #4335).
 *
 * Saves the current targets, their changed options and the first ticked delivery profile as a named
 * preset. The REST layer validates every option against its emitter's schema; a refusal lists each
 * problem.
 *
 * @param props See {@link SavePresetFormProps}.
 * @returns The button, then the form once opened.
 */
export function SavePresetForm({ targets, deliveryProfileId }: SavePresetFormProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<{ message: string; errors: string[] } | null>(null);

  if (targets.length === 0) return null;

  const save = async () => {
    if (!name.trim()) {
      setError({ message: 'Name the preset.', errors: [] });
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const preset = await createExportPreset(presetBody(name, description, targets, deliveryProfileId));
      setSaved(preset.name);
      setOpen(false);
      setName('');
      setDescription('');
    } catch (cause) {
      setError({
        message: cause instanceof Error ? cause.message : 'Could not save the preset',
        errors: cause instanceof ExportPresetsError ? cause.errors : [],
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="xdlv-job" aria-label="Save as preset" data-testid="export-preset-save">
      {!open ? (
        <div className="xdlv-job__now">
          <Button size="sm" variant="outline" onClick={() => { setOpen(true); setSaved(null); }}>
            <Bookmark className="h-4 w-4" aria-hidden />
            Save as preset
          </Button>
          {saved ? <span className="xdlv-quiet" role="status">Saved preset {saved}.</span> : null}
        </div>
      ) : (
        <div className="xdlv-form">
          <p className="xdlv-quiet">
            Saves <span className="mono">{targetsSummary(targets)}</span>
            {deliveryProfileId ? ' and the ticked delivery profile' : ''}.
          </p>
          <div className="xdlv-field">
            <Label htmlFor="xprs-save-name">Preset name</Label>
            <Input id="xprs-save-name" value={name} maxLength={120} placeholder="nightly-sync"
              onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="xdlv-field">
            <Label htmlFor="xprs-save-description">Description</Label>
            <Input id="xprs-save-description" value={description} placeholder="What this preset is for"
              onChange={(event) => setDescription(event.target.value)} />
          </div>
          {error ? (
            <div className="xdlv-job__error" role="alert">
              {error.message}
              {error.errors.length > 0 ? (
                <ul className="xdlv-problems">
                  {error.errors.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <div className="xdlv-form__actions">
            <Button size="sm" variant="outline" disabled={saving} onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button size="sm" disabled={saving} onClick={() => void save()} data-testid="xprs-save-preset">
              Save preset
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

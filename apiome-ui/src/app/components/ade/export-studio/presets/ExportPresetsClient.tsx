'use client';

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Bookmark, Plus, Trash2 } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { Textarea } from '@/app/components/ui/Textarea';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { fetchMyPermissions, type MyPermissions } from '@/app/ade/dashboard/style-guides/api';

import { fetchDeliveryProfiles } from '../delivery/deliveryProfilesApi';
import { AutoExportPanel } from './AutoExportPanel';
import type { DeliveryProfile } from '../delivery/deliveryProfilesModel';
import {
  ExportPresetsError,
  deleteExportPreset,
  fetchExportPresets,
  updateExportPreset,
} from './exportPresetsApi';
import { EXPORT_STUDIO_PATH } from '../../dashboard/export/exportStudioLink';
import {
  MAX_PRESET_DELIVERY_PROFILES,
  MAX_PRESET_TARGETS,
  draftFromPreset,
  presetProfileNames,
  targetsSummary,
  updateFromDraft,
  type ExportPreset,
  type PresetDraft,
} from './exportPresetsModel';

/** Props for {@link ExportPresetsClient}. */
export interface ExportPresetsClientProps {
  /** The Export studio tab strip, drawn under the header. */
  tabs?: ReactNode;
}

/**
 * Export studio's **Presets** tab — the workspace's export presets (MFX-39.3, #4335).
 *
 * A preset saves an export's targets, each target's options and up to five delivery profiles once, by
 * name. A preset is made on the export's **Review** step (**Save as preset**) and applied on its
 * **Target** step (**Apply a preset**), from **Open in Studio** here (MFX-46.4: the studio opens on the
 * Source picker and applies the preset once a source is chosen), or from the CLI (`apiome export
 * --preset NAME`); this tab lists them, edits a preset's name, description, targets and delivery
 * profiles, and deletes it. The REST layer validates every
 * target's options against its emitter's schema and lists every problem; members without
 * `projects:edit` see the presets read-only.
 *
 * @param props See {@link ExportPresetsClientProps}.
 * @returns The tab.
 */
export default function ExportPresetsClient({ tabs }: ExportPresetsClientProps = {}) {
  const [presets, setPresets] = useState<ExportPreset[]>([]);
  const [profiles, setProfiles] = useState<DeliveryProfile[]>([]);
  const [permissions, setPermissions] = useState<MyPermissions | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ExportPreset | null>(null);
  const [draft, setDraft] = useState<PresetDraft | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  // MFX-39.4: the preset whose auto-export-on-publish panel is open (instead of the edit form).
  const [autoPreset, setAutoPreset] = useState<ExportPreset | null>(null);

  const canEdit = permissions
    ? permissions.is_admin === true ||
      (Array.isArray(permissions.permissions) && permissions.permissions.includes('projects:edit'))
    : false;

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setPresets(await fetchExportPresets());
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : 'Could not load the export presets');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    let live = true;
    void Promise.all([fetchDeliveryProfiles().catch(() => []), fetchMyPermissions()]).then(([rows, perms]) => {
      if (!live) return;
      setProfiles(rows);
      setPermissions(perms);
    });
    return () => {
      live = false;
    };
  }, [reload]);

  const startEdit = (preset: ExportPreset) => {
    setAutoPreset(null);
    setEditing(preset);
    setDraft(draftFromPreset(preset));
    setProblems([]);
    setSaveError(null);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!editing || !draft) return;
    const { body, problems: found } = updateFromDraft(draft);
    setProblems(found);
    setSaveError(null);
    if (!body) return;
    setSaving(true);
    try {
      await updateExportPreset(editing.id, body);
      setEditing(null);
      setDraft(null);
      await reload();
    } catch (cause) {
      setSaveError(cause instanceof Error ? cause.message : 'Could not save the preset');
      setProblems(cause instanceof ExportPresetsError ? cause.errors : []);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (preset: ExportPreset) => {
    setSaving(true);
    try {
      await deleteExportPreset(preset.id);
      setConfirmDelete(null);
      if (editing?.id === preset.id) {
        setEditing(null);
        setDraft(null);
      }
      await reload();
    } catch (cause) {
      setLoadError(cause instanceof Error ? cause.message : 'Could not delete the preset');
    } finally {
      setSaving(false);
    }
  };

  const setRow = (index: number, patch: Partial<PresetDraft['targets'][number]>) =>
    setDraft((current) =>
      current
        ? { ...current, targets: current.targets.map((row, i) => (i === index ? { ...row, ...patch } : row)) }
        : current,
    );

  return (
    <Page data-testid="export-presets">
      <PageHeader
        breadcrumb={[{ label: 'Home', href: '/ade/dashboard' }, { label: 'Ship' }, { label: 'Export studio' }]}
        title="Export studio"
        description="Saved export combinations — targets, their options and delivery — applied by name."
        tabs={tabs}
      />
      <PageBody>
        {!canEdit && permissions !== null ? (
          <Alert variant="info" className="xdlv-notice">
            Read-only for members. Changing export presets needs <code className="mono">projects:edit</code>.
          </Alert>
        ) : null}
        {loadError ? (
          <Alert variant="danger" className="xdlv-notice">
            {loadError}
          </Alert>
        ) : null}

        <div className="xdlv-layout">
          <section aria-label="Export presets">
            {loading ? (
              <div data-testid="xprs-loading">
                <span className="sr-only" role="status">
                  Loading export presets…
                </span>
                <Skeleton className="xdlv-skeleton" />
                <Skeleton className="xdlv-skeleton" />
              </div>
            ) : presets.length === 0 ? (
              <EmptyState
                icon={<Bookmark />}
                title="No export presets yet"
                description="On an export's Review step, click Save as preset to keep its targets."
              />
            ) : (
              <ul className="xdlv-profiles">
                {presets.map((preset) => (
                  <li key={preset.id} className="xdlv-profile" data-testid="xprs-preset"
                    data-selected={editing?.id === preset.id || autoPreset?.id === preset.id}>
                    <div className="xdlv-profile__head">
                      <span className="xdlv-profile__name">{preset.name}</span>
                      <span className="xdlv-profile__channel">
                        {preset.targets.length === 1 ? '1 target' : `${preset.targets.length} targets`}
                      </span>
                    </div>
                    <p className="xdlv-profile__dest mono">{targetsSummary(preset.targets)}</p>
                    <p className="xdlv-quiet">
                      {presetProfileNames(preset).length
                        ? `Delivered with ${presetProfileNames(preset).join(', ')}`
                        : 'No delivery'}
                      {preset.description ? ` · ${preset.description}` : ''}
                    </p>
                    <p className="xdlv-quiet">
                      CLI: <code className="mono">apiome export --preset {preset.name} ARTIFACT --out PATH</code>
                    </p>
                    <div className="xdlv-profile__actions">
                      <a className="xdlv-job__manage" data-testid="xprs-open-studio"
                        href={`${EXPORT_STUDIO_PATH}?preset=${encodeURIComponent(preset.id)}`}>
                        Open in Studio
                      </a>
                      <Button size="sm" variant="ghost" onClick={() => { setEditing(null); setDraft(null); setAutoPreset(preset); }}>
                        Auto-export
                      </Button>
                    {canEdit ? (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => startEdit(preset)}>
                          Edit
                        </Button>
                        {confirmDelete === preset.id ? (
                          <>
                            <Button title={saving ? 'Wait for the save to finish' : undefined} size="sm" variant="danger" disabled={saving} onClick={() => void remove(preset)}>
                              Delete {preset.name}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                              Keep
                            </Button>
                          </>
                        ) : (
                          <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(preset.id)}>
                            Delete
                          </Button>
                        )}
                      </>
                    ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {autoPreset ? <AutoExportPanel key={autoPreset.id} scope={{ kind: 'preset', preset: autoPreset }} canEdit={canEdit} /> : null}

          {editing && draft ? (
            <section className="xdlv-panel" aria-label={`Edit ${editing.name}`}>
              <h2 className="xdlv-panel__title">Edit {editing.name}</h2>
              <form className="xdlv-form" onSubmit={(event) => void save(event)} noValidate>
                {saveError || problems.length > 0 ? (
                  <Alert variant="danger">
                    {saveError ?? 'Fix these before saving:'}
                    {problems.length > 0 ? (
                      <ul className="xdlv-problems">
                        {problems.map((problem) => (
                          <li key={problem}>{problem}</li>
                        ))}
                      </ul>
                    ) : null}
                  </Alert>
                ) : null}
                <div className="xdlv-field">
                  <Label htmlFor="xprs-name">Name</Label>
                  <Input id="xprs-name" value={draft.name} maxLength={120}
                    onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
                </div>
                <div className="xdlv-field">
                  <Label htmlFor="xprs-description">Description</Label>
                  <Input id="xprs-description" value={draft.description}
                    onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
                </div>
                <fieldset className="xdlv-field">
                  <legend className="xdlv-legend">Targets</legend>
                  {draft.targets.map((row, index) => (
                    <div key={index} className="xdlv-group xprs-target" data-testid="xprs-target-row">
                      <div className="xdlv-field">
                        <Label htmlFor={`xprs-target-${index}`}>Target {index + 1}</Label>
                        <div className="xprs-target__head">
                          <Input id={`xprs-target-${index}`} value={row.target} placeholder="openapi-3.1"
                            onChange={(event) => setRow(index, { target: event.target.value })} />
                          <Button title={draft.targets.length <= 1 ? 'A preset needs at least one target' : undefined} type="button" size="sm" variant="ghost" aria-label={`Remove target ${index + 1}`}
                            disabled={draft.targets.length <= 1}
                            onClick={() => setDraft({ ...draft, targets: draft.targets.filter((_, i) => i !== index) })}>
                            <Trash2 className="h-4 w-4" aria-hidden />
                          </Button>
                        </div>
                      </div>
                      <div className="xdlv-field">
                        <Label htmlFor={`xprs-options-${index}`}>Options (JSON)</Label>
                        <Textarea id={`xprs-options-${index}`} className="mono" rows={3} value={row.optionsText}
                          placeholder='{"openapi_version": "3.0"}'
                          onChange={(event) => setRow(index, { optionsText: event.target.value })} />
                      </div>
                    </div>
                  ))}
                  <div>
                    <Button title={draft.targets.length >= MAX_PRESET_TARGETS ? `A preset holds at most ${MAX_PRESET_TARGETS} targets` : undefined} type="button" size="sm" variant="outline" disabled={draft.targets.length >= MAX_PRESET_TARGETS}
                      onClick={() => setDraft({ ...draft, targets: [...draft.targets, { target: '', optionsText: '' }] })}>
                      <Plus className="h-4 w-4" aria-hidden />
                      Add target
                    </Button>
                  </div>
                </fieldset>
                <fieldset className="xdlv-field" data-testid="xprs-delivery">
                  <legend className="xdlv-legend">Delivery profiles</legend>
                  <p className="xdlv-hint">
                    Up to {MAX_PRESET_DELIVERY_PROFILES}, delivered in the order ticked. None ticked: export only.
                  </p>
                  {profiles.length === 0 ? (
                    <p className="xdlv-quiet">No delivery profiles in this workspace.</p>
                  ) : (
                    profiles.map((profile) => {
                      const position = draft.deliveryProfileIds.indexOf(profile.id);
                      const ticked = position >= 0;
                      return (
                        <label key={profile.id} className="xdlv-choice">
                          <input type="checkbox" checked={ticked}
                            disabled={!ticked && draft.deliveryProfileIds.length >= MAX_PRESET_DELIVERY_PROFILES}
                            onChange={(event) => setDraft({
                              ...draft,
                              deliveryProfileIds: event.target.checked
                                ? [...draft.deliveryProfileIds, profile.id]
                                : draft.deliveryProfileIds.filter((id) => id !== profile.id),
                            })} />
                          <span className="xdlv-choice__name">{profile.name}</span>
                          {ticked ? <span className="xdlv-choice__meta">#{position + 1}</span> : null}
                        </label>
                      );
                    })
                  )}
                </fieldset>
                <div className="xdlv-form__actions">
                  <Button title={saving ? 'Wait for the save to finish' : undefined} type="button" variant="outline" disabled={saving}
                    onClick={() => { setEditing(null); setDraft(null); }}>
                    Cancel
                  </Button>
                  <Button title={saving ? 'Saving the preset' : undefined} type="submit" disabled={saving} data-testid="xprs-save">
                    Save changes
                  </Button>
                </div>
              </form>
            </section>
          ) : null}
        </div>
      </PageBody>
    </Page>
  );
}

'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Award,
  Flag,
  Users,
  Plus,
  Pencil,
  Trash2,
  RefreshCw,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  X,
  Link,
  Eye,
  ToggleLeft,
  ToggleRight,
  ShieldCheck,
  Package,
} from 'lucide-react';
import {
  getAllLicenses,
  createLicense,
  updateLicense,
  deleteLicense,
  getAllFeatureFlags,
  createFeatureFlag,
  updateFeatureFlag,
  deleteFeatureFlag,
  getAllFeatureFlagGroups,
  createFeatureFlagGroup,
  updateFeatureFlagGroup,
  deleteFeatureFlagGroup,
  getAllUsersWithLicenses,
  assignLicenseToUser,
  removeUserLicense,
} from '../../../../../lib/db/admin-actions';
import { isCommercialProductFlag } from '../../../../../lib/commercial-products';
import { FeatureFlagUserOverridesPanel } from '../components/FeatureFlagUserOverridesPanel';
import { TAB_LIST_CLASS, tabTriggerClass } from '@/app/components/ui/tabStyles';
import { useDialog } from '@/app/components/providers/DialogProvider';
import { ModalFrame, ModalFrameTitle } from '@/app/components/ui/ModalFrame';
import { destructiveConfirm } from '@/app/components/dialogs/destructiveConfirm';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { SkeletonCardGrid, SkeletonText } from '@/app/components/ui/Skeleton';
import { Input } from '@/app/components/ui/Input';
import { Textarea } from '@/app/components/ui/Textarea';

// ─── Types ───────────────────────────────────────────────────────────────────

interface FeatureFlagRef {
  id: string;
  name: string;
  label: string;
  is_preview: boolean;
}

interface License {
  id: string;
  name: string;
  description: string | null;
  license_type: 'free' | 'paid' | 'sponsor';
  seats: Record<string, number>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  feature_flags: FeatureFlagRef[];
}

interface FeatureFlag {
  id: string;
  name: string;
  label: string;
  description: string | null;
  url_patterns: string[];
  is_preview: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

interface UserWithLicense {
  id: string;
  name: string;
  email: string;
  enabled: boolean;
  verified: boolean;
  license_id: string | null;
  license_name: string | null;
  license_type: string | null;
  seats: Record<string, number> | null;
  plan_code: string | null;
}

type LicenseManagementTab = 'licenses' | 'featureFlags' | 'flagPackages' | 'assignments';

interface FeatureFlagGroup {
  id: string;
  name: string;
  label: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  feature_flags: FeatureFlagRef[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  free:    'bg-inset text-fg-muted',
  paid:    'bg-accent text-fg-on-accent',
  sponsor: 'bg-warn text-fg-on-accent',
};

/** Canonical / common `licenses.seats` keys (JSONB). Custom keys are allowed. */
const SEAT_LIMIT_PRESETS: { key: string; description: string }[] = [
  { key: 'max_tenants', description: 'Maximum tenant workspaces' },
  { key: 'max_users_per_tenant', description: 'Maximum users allowed per tenant' },
  { key: 'max_projects', description: 'Maximum catalog projects' },
  { key: 'max_versions', description: 'Maximum versions per project' },
  { key: 'max_ai_requests', description: 'Maximum AI assistant requests (0 = none, -1 = unlimited)' },
];

type SeatEntryRow = { id: string; key: string; value: number; keySource: 'preset' | 'custom' };

function newSeatRowId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

function seatsRecordToRows(seats: Record<string, number>): SeatEntryRow[] {
  return Object.entries(seats).map(([key, value]) => {
    const preset = SEAT_LIMIT_PRESETS.some((p) => p.key === key);
    return {
      id: newSeatRowId(),
      key,
      value: Number.isFinite(Number(value)) ? Number(value) : 0,
      keySource: preset ? 'preset' : 'custom',
    };
  });
}

function defaultSeatRows(): SeatEntryRow[] {
  return [
    { id: newSeatRowId(), key: 'max_tenants', value: 1, keySource: 'preset' },
    { id: newSeatRowId(), key: 'max_users_per_tenant', value: 5, keySource: 'preset' },
  ];
}

function buildSeatsFromRows(rows: SeatEntryRow[]): { ok: true; seats: Record<string, number> } | { ok: false; error: string } {
  const out: Record<string, number> = {};
  const seen = new Set<string>();
  for (const row of rows) {
    const k = row.key.trim();
    if (!k) {
      return { ok: false, error: 'Every seat limit needs a key (pick a preset or enter a custom key).' };
    }
    if (seen.has(k)) {
      return { ok: false, error: `Duplicate seat key "${k}". Each key can only appear once.` };
    }
    seen.add(k);
    const n = row.value;
    if (!Number.isFinite(n) || !Number.isInteger(n) || n < 0) {
      return { ok: false, error: `Value for "${k}" must be a non-negative whole number.` };
    }
    out[k] = n;
  }
  return { ok: true, seats: out };
}

function Badge({ type }: { type: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-xs text-2xs font-semibold uppercase tracking-wide ${TYPE_COLORS[type] ?? 'bg-inset text-fg-muted'}`}>
      {type}
    </span>
  );
}

function PreviewBadge() {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-xs text-2xs font-semibold uppercase bg-warn/40 text-warn-fg border border-warn/40">
      <Eye className="w-3 h-3" /> Preview
    </span>
  );
}

function LicenseSeatEntriesEditor({
  rows,
  onChange,
}: {
  rows: SeatEntryRow[];
  onChange: (next: SeatEntryRow[]) => void;
}) {
  const presetKeySet = useMemo(() => new Set(SEAT_LIMIT_PRESETS.map((p) => p.key)), []);

  const updateRow = useCallback(
    (id: string, patch: Partial<SeatEntryRow>) => {
      onChange(rows.map((x) => (x.id === id ? { ...x, ...patch } : x)));
    },
    [rows, onChange]
  );

  const removeRow = useCallback(
    (id: string) => {
      onChange(rows.filter((x) => x.id !== id));
    },
    [rows, onChange]
  );

  const addRow = useCallback(() => {
    const taken = new Set(rows.map((r) => r.key.trim()).filter(Boolean));
    const nextPreset = SEAT_LIMIT_PRESETS.find((p) => !taken.has(p.key));
    if (nextPreset) {
      onChange([
        ...rows,
        { id: newSeatRowId(), key: nextPreset.key, value: 0, keySource: 'preset' },
      ]);
    } else {
      onChange([...rows, { id: newSeatRowId(), key: '', value: 0, keySource: 'custom' }]);
    }
  }, [rows, onChange]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">
            Seat limits (quotas)
          </label>
          <p className="mt-0.5 max-w-xl text-xs text-fg-muted">
            Stored as numeric key/value pairs on the license. Pick a preset or add a custom key. Feature access is
            configured separately in <span className="font-medium text-fg-muted">Included Feature Flags</span>{' '}
            below.
          </p>
        </div>
        <Button
          type="button"
          onClick={addRow}
          variant="accent" size="sm" className="shrink-0 border-accent text-xs text-accent-fg"
        >
          <Plus className="h-3.5 w-3.5 shrink-0 text-accent-fg" aria-hidden />
          Add limit
        </Button>
      </div>

      <div className="space-y-2">
        {rows.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border-strong px-3 py-6 text-center text-sm text-fg-muted">
            No seat limits yet. Click <span className="font-medium">Add limit</span> to add quotas.
          </p>
        ) : (
          rows.map((row) => {
            const takenByOther = (k: string) => rows.some((r) => r.id !== row.id && r.key.trim() === k);
            const isPresetRow = row.keySource === 'preset' && presetKeySet.has(row.key);
            const selectValue =
              row.key.trim() === '' ? '' : isPresetRow ? row.key : '__custom__';

            return (
              <div
                key={row.id}
                className="flex flex-wrap items-end gap-2 rounded-lg border border-border-strong bg-subtle/80 p-3"
              >
                <div className="min-w-[200px] flex-1 space-y-1">
                  <span className="text-2xs font-medium uppercase tracking-wide text-fg-muted">
                    Key
                  </span>
                  <select
                    value={selectValue}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === '') {
                        updateRow(row.id, { key: '', keySource: 'preset' });
                      } else if (v === '__custom__') {
                        updateRow(row.id, {
                          keySource: 'custom',
                          key: presetKeySet.has(row.key) ? '' : row.key,
                        });
                      } else {
                        updateRow(row.id, { key: v, keySource: 'preset' });
                      }
                    }}
                    className="hive-control h-[var(--control-h)] w-full rounded-md bg-surface px-3 text-sm text-fg focus-visible:outline-none"
                  >
                    <option value="">Select a limit…</option>
                    {SEAT_LIMIT_PRESETS.map((p) => (
                      <option key={p.key} value={p.key} disabled={takenByOther(p.key)}>
                        {p.key}
                      </option>
                    ))}
                    <option value="__custom__">Custom key…</option>
                  </select>
                  {isPresetRow ? (
                    <p className="text-2xs leading-snug text-fg-muted">
                      {SEAT_LIMIT_PRESETS.find((p) => p.key === row.key)?.description}
                    </p>
                  ) : null}
                </div>
                {selectValue === '__custom__' ? (
                  <div className="min-w-[160px] flex-1 space-y-1">
                    <span className="text-2xs font-medium uppercase tracking-wide text-fg-muted">
                      Custom key
                    </span>
                    <Input
                      value={row.keySource === 'custom' || !presetKeySet.has(row.key) ? row.key : ''}
                      onChange={(e) =>
                        updateRow(row.id, { key: e.target.value, keySource: 'custom' })
                      }
                      placeholder="e.g. max_branches"
                      className="font-mono"
                    />
                  </div>
                ) : null}
                <div className="w-28 space-y-1">
                  <span className="text-2xs font-medium uppercase tracking-wide text-fg-muted">
                    Value
                  </span>
                  <Input
                    type="number"
                    min={0}
                    step={1}
                    value={Number.isFinite(row.value) ? row.value : 0}
                    onChange={(e) => {
                      const n = parseInt(e.target.value, 10);
                      updateRow(row.id, { value: Number.isFinite(n) && n >= 0 ? n : 0 });
                    }}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => removeRow(row.id)}
                  className="mb-0.5 rounded-lg p-2 text-fg-muted hover:bg-danger/20 hover:text-danger-fg"
                  title="Remove this limit"
                  aria-label="Remove seat limit row"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ─── License form ────────────────────────────────────────────────────────────

interface LicenseFormProps {
  existing?: License | null;
  allFlags: FeatureFlag[];
  onSave: () => void;
  onCancel: () => void;
}

function LicenseForm({ existing, allFlags, onSave, onCancel }: LicenseFormProps) {
  const [name, setName] = useState(existing?.name ?? '');
  const [description, setDescription] = useState(existing?.description ?? '');
  const [licenseType, setLicenseType] = useState<'free' | 'paid' | 'sponsor'>(existing?.license_type ?? 'free');
  const [seatRows, setSeatRows] = useState<SeatEntryRow[]>(() =>
    existing ? seatsRecordToRows(existing.seats) : defaultSeatRows()
  );
  const [seatError, setSeatError] = useState('');
  const [selectedFlags, setSelectedFlags] = useState<Set<string>>(
    new Set(existing?.feature_flags.map(f => f.id) ?? [])
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setSeatError('');
  }, [seatRows]);

  const toggleFlag = (id: string) => {
    setSelectedFlags(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const built = buildSeatsFromRows(seatRows);
    if (!built.ok) {
      setSeatError(built.error);
      return;
    }
    setSeatError('');
    if (!name.trim()) { setError('Name is required'); return; }

    setSaving(true);
    setError('');
    try {
      let res: string;
      if (existing) {
        res = await updateLicense(existing.id, {
          name: name.trim(), description: description || null,
          licenseType, seats: built.seats, featureFlagIds: [...selectedFlags],
        });
      } else {
        res = await createLicense(name.trim(), description || null, licenseType, built.seats, [...selectedFlags]);
      }
      const data = JSON.parse(res);
      if (!data.success) { setError(data.error); return; }
      onSave();
    } catch {
      setError('Unexpected error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/20 border border-danger rounded-lg text-danger-fg text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />{error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Name *</label>
          <Input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="e.g. Paid"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Type *</label>
          <select
            value={licenseType}
            onChange={e => setLicenseType(e.target.value as 'free' | 'paid' | 'sponsor')}
            className="hive-control h-[var(--control-h)] w-full rounded-md bg-surface px-3 text-sm text-fg focus-visible:outline-none"
          >
            <option value="free">Free</option>
            <option value="paid">Paid</option>
            <option value="sponsor">Sponsor</option>
          </select>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Description</label>
        <Textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          className="resize-none"
          placeholder="Short description of this license tier"
        />
      </div>

      <div className="space-y-1">
        <LicenseSeatEntriesEditor rows={seatRows} onChange={setSeatRows} />
        {seatError && <p className="text-xs text-danger-fg">{seatError}</p>}
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">
          Commercial products &amp; features
        </label>
        <p className="text-xs text-fg-muted">
          Toggle which applications appear on the home page and top navigation for users assigned this license.
        </p>
        {allFlags.length === 0 ? (
          <p className="text-xs text-fg-muted italic">No feature flags defined yet.</p>
        ) : (
          <div className="space-y-4">
            {(['products', 'features'] as const).map((section) => {
              const sectionFlags = allFlags.filter((ff) =>
                section === 'products' ? isCommercialProductFlag(ff.name) : !isCommercialProductFlag(ff.name)
              );
              if (sectionFlags.length === 0) return null;
              return (
                <div key={section} className="space-y-2">
                  <p className="text-2xs font-semibold uppercase tracking-wide text-fg-muted">
                    {section === 'products' ? 'Commercial applications' : 'Additional platform features'}
                  </p>
                  <div className="grid grid-cols-2 gap-2">
                    {sectionFlags.map((ff) => (
                      <label
                        key={ff.id}
                        className={`flex items-start gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                          selectedFlags.has(ff.id)
                            ? 'bg-accent/30 border-accent'
                            : 'bg-subtle border-border-strong hover:border-border-strong'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={selectedFlags.has(ff.id)}
                          onChange={() => toggleFlag(ff.id)}
                          className="mt-0.5 accent-accent"
                        />
                        <span className="flex flex-col min-w-0">
                          <span className="text-sm text-fg font-medium flex items-center gap-1.5">
                            {ff.label}
                            {ff.is_preview && <PreviewBadge />}
                          </span>
                          <span className="text-xs text-fg-muted truncate">{ff.name}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      </div>

      <div className="mt-4 flex shrink-0 justify-end gap-2 border-t border-border pt-4">
        <Button type="button" onClick={onCancel} variant="outline">
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={saving}
          variant="accent"
        >
          {saving ? 'Saving…' : existing ? 'Save Changes' : 'Create License'}
        </Button>
      </div>
    </form>
  );
}

// ─── Feature flag form ────────────────────────────────────────────────────────

interface FlagFormProps {
  existing?: FeatureFlag | null;
  onSave: () => void;
  onCancel: () => void;
}

function FlagForm({ existing, onSave, onCancel }: FlagFormProps) {
  const [name, setName] = useState(existing?.name ?? '');
  const [label, setLabel] = useState(existing?.label ?? '');
  const [description, setDescription] = useState(existing?.description ?? '');
  const [urlsRaw, setUrlsRaw] = useState((existing?.url_patterns ?? []).join('\n'));
  const [isPreview, setIsPreview] = useState(existing?.is_preview ?? false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !label.trim()) { setError('Name and Label are required'); return; }
    if (!/^[a-z0-9_]+$/.test(name.trim())) { setError('Name must be lowercase alphanumeric + underscores only'); return; }

    const urlPatterns = urlsRaw.split('\n').map(s => s.trim()).filter(Boolean);
    setSaving(true);
    setError('');
    try {
      let res: string;
      if (existing) {
        res = await updateFeatureFlag(existing.id, { label: label.trim(), description: description || null, urlPatterns, isPreview });
      } else {
        res = await createFeatureFlag(name.trim(), label.trim(), description || null, urlPatterns, isPreview);
      }
      const data = JSON.parse(res);
      if (!data.success) { setError(data.error); return; }
      onSave();
    } catch {
      setError('Unexpected error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/20 border border-danger rounded-lg text-danger-fg text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />{error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Machine Name *</label>
          <Input
            value={name}
            onChange={e => setName(e.target.value)}
            disabled={!!existing}
            className="font-mono"
            placeholder="ai_assistant"
          />
          <p className="text-xs text-fg-muted">Lowercase, underscores only. Cannot be changed after creation.</p>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Display Label *</label>
          <Input
            value={label}
            onChange={e => setLabel(e.target.value)}
            placeholder="AI Assistant"
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Description</label>
        <Textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          className="resize-none"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-fg-muted uppercase tracking-wide flex items-center gap-1.5">
          <Link className="w-3.5 h-3.5" /> URL Patterns (one per line)
        </label>
        <p className="text-xs text-fg-muted">Paths that require this flag to be active. E.g. <code className="text-fg-subtle">/ade/studio</code> or <code className="text-fg-subtle">/api/ollama</code></p>
        <Textarea
          value={urlsRaw}
          onChange={e => setUrlsRaw(e.target.value)}
          rows={4}
          className="text-ok-fg font-mono resize-none"
          placeholder={`/ade/studio\n/api/ollama`}
        />
      </div>

      <label className="flex items-center gap-3 cursor-pointer select-none">
        <button
          type="button"
          onClick={() => setIsPreview(!isPreview)}
          className="text-accent-fg hover:text-accent-fg"
        >
          {isPreview ? <ToggleRight className="w-6 h-6" /> : <ToggleLeft className="w-6 h-6 text-fg-muted" />}
        </button>
        <span className="text-sm text-fg-muted">Mark as <strong>Preview</strong> (shows preview badge in UI)</span>
      </label>

      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" onClick={onCancel} variant="outline">
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={saving}
          variant="accent"
        >
          {saving ? 'Saving…' : existing ? 'Save Changes' : 'Create Flag'}
        </Button>
      </div>
    </form>
  );
}

// ─── Feature flag package form ───────────────────────────────────────────────

interface FlagPackageFormProps {
  existing?: FeatureFlagGroup | null;
  allFlags: FeatureFlag[];
  onSave: () => void;
  onCancel: () => void;
}

function FlagPackageForm({ existing, allFlags, onSave, onCancel }: FlagPackageFormProps) {
  const [name, setName] = useState(existing?.name ?? '');
  const [label, setLabel] = useState(existing?.label ?? '');
  const [description, setDescription] = useState(existing?.description ?? '');
  const [selected, setSelected] = useState<Set<string>>(
    new Set(existing?.feature_flags.map(f => f.id) ?? [])
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const toggle = (id: string) => {
    setSelected(prev => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !label.trim()) {
      setError('Name and Label are required');
      return;
    }
    if (!/^[a-z0-9_]+$/.test(name.trim())) {
      setError('Name must be lowercase alphanumeric + underscores only');
      return;
    }
    setSaving(true);
    setError('');
    try {
      let res: string;
      const ids = [...selected];
      if (existing) {
        res = await updateFeatureFlagGroup(existing.id, {
          label: label.trim(),
          description: description.trim() || null,
          featureFlagIds: ids,
        });
      } else {
        res = await createFeatureFlagGroup(
          name.trim(),
          label.trim(),
          description.trim() || null,
          ids
        );
      }
      const data = JSON.parse(res);
      if (!data.success) {
        setError(data.error);
        return;
      }
      onSave();
    } catch {
      setError('Unexpected error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/20 border border-danger rounded-lg text-danger-fg text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1">
          <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Machine Name *</label>
          <Input
            value={name}
            onChange={e => setName(e.target.value)}
            disabled={!!existing}
            className="font-mono"
            placeholder="standard_features"
          />
          <p className="text-xs text-fg-muted">Cannot be changed after creation.</p>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Display Label *</label>
          <Input
            value={label}
            onChange={e => setLabel(e.target.value)}
            placeholder="Standard features"
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Description</label>
        <Textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          className="resize-none"
        />
      </div>

      <div className="space-y-2">
        <label className="text-xs font-medium text-fg-muted uppercase tracking-wide">Flags in this package</label>
        {allFlags.length === 0 ? (
          <p className="text-xs text-fg-muted italic">Create feature flags first.</p>
        ) : (
          <div className="max-h-48 overflow-y-auto rounded-lg border border-border divide-y divide-border">
            {allFlags.map(ff => (
              <label
                key={ff.id}
                className={`flex items-start gap-3 px-3 py-2 cursor-pointer select-none ${
                  selected.has(ff.id)
                    ? 'bg-accent/20 border-l-2 border-l-accent'
                    : 'hover:bg-subtle'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(ff.id)}
                  onChange={() => toggle(ff.id)}
                  className="mt-1 accent-accent"
                />
                <span className="flex flex-col min-w-0">
                  <span className="text-sm text-fg font-medium flex items-center gap-1.5">
                    {ff.label}
                    {ff.is_preview && <PreviewBadge />}
                  </span>
                  <span className="text-xs text-fg-muted font-mono truncate">{ff.name}</span>
                </span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <Button
          type="button"
          onClick={onCancel}
          variant="outline"
        >
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={saving}
          variant="accent"
        >
          {saving ? 'Saving…' : existing ? 'Save Package' : 'Create Package'}
        </Button>
      </div>
    </form>
  );
}

// ─── Modal wrapper ────────────────────────────────────────────────────────────

function Modal({
  title,
  onClose,
  children,
  fixedViewportHeight = false,
  panelClassName,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  /** When true, dialog is exactly 90vh tall and only the body scrolls (stable layout). */
  fixedViewportHeight?: boolean;
  /** Extra classes on the dialog panel (e.g. max width). */
  panelClassName?: string;
}) {
  // A Radix dialog under the existing look (HIVE-10.2): focus is trapped while open and returns
  // to the trigger on close; Escape and the backdrop close it.
  return (
    <ModalFrame
      open
      onClose={onClose}
      overlayClassName="fixed inset-0 z-50 flex items-center justify-center bg-overlay backdrop-blur-sm p-4"
      className={`bg-surface border border-border rounded-xl shadow-lg w-full flex flex-col overflow-hidden ${
        fixedViewportHeight
          ? 'h-[90vh] max-h-[90vh] max-w-4xl'
          : 'max-w-2xl max-h-[90vh] overflow-y-auto'
      } ${panelClassName ?? ''}`.trim()}
    >
        <div className="flex shrink-0 items-center justify-between px-6 py-4 border-b border-border">
          <ModalFrameTitle asChild>
            <h3 className="text-fg font-semibold text-lg">{title}</h3>
          </ModalFrameTitle>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="hit-target text-fg-muted hover:text-fg-muted transition-colors"
          >
            <X className="w-5 h-5" aria-hidden />
          </button>
        </div>
        <div
          className={
            fixedViewportHeight
              ? 'flex min-h-0 flex-1 flex-col overflow-hidden px-6 py-5'
              : 'px-6 py-5'
          }
        >
          {children}
        </div>
    </ModalFrame>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function LicenseManagementClient({
  initialTab = 'licenses',
}: {
  initialTab?: LicenseManagementTab;
} = {}) {
  const { confirm } = useDialog();
  const [activeTab, setActiveTab] = useState<LicenseManagementTab>(initialTab);
  const [licenses, setLicenses] = useState<License[]>([]);
  const [featureFlags, setFeatureFlags] = useState<FeatureFlag[]>([]);
  const [flagGroups, setFlagGroups] = useState<FeatureFlagGroup[]>([]);
  const [usersWithLicenses, setUsersWithLicenses] = useState<UserWithLicense[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Modals
  const [licenseModal, setLicenseModal] = useState<'create' | 'edit' | null>(null);
  const [flagModal, setFlagModal] = useState<'create' | 'edit' | null>(null);
  const [packageModal, setPackageModal] = useState<'create' | 'edit' | null>(null);
  const [editingLicense, setEditingLicense] = useState<License | null>(null);
  const [editingFlag, setEditingFlag] = useState<FeatureFlag | null>(null);
  const [editingPackage, setEditingPackage] = useState<FeatureFlagGroup | null>(null);

  // Expanded licenses (to show feature flags)
  const [expandedLicenses, setExpandedLicenses] = useState<Set<string>>(new Set());

  // Assign dropdown
  const [assigningUser, setAssigningUser] = useState<UserWithLicense | null>(null);
  const [assignSearch, setAssignSearch] = useState('');

  // Flag override modal
  const [overrideUser, setOverrideUser] = useState<UserWithLicense | null>(null);

  const showMessage = (type: 'success' | 'error', text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 5000);
  };

  const loadAll = async () => {
    setLoading(true);
    try {
      const [lr, ffr, ur, gr] = await Promise.all([
        getAllLicenses(),
        getAllFeatureFlags(),
        getAllUsersWithLicenses(),
        getAllFeatureFlagGroups(),
      ]);
      const ld = JSON.parse(lr); if (ld.success) setLicenses(ld.licenses);
      const fd = JSON.parse(ffr); if (fd.success) setFeatureFlags(fd.featureFlags);
      const ud = JSON.parse(ur); if (ud.success) setUsersWithLicenses(ud.users);
      const gd = JSON.parse(gr);
      setFlagGroups(gd.success ? (gd.groups ?? []) : []);
    } catch {
      showMessage('error', 'Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  // ── License tab ───────────────────────────────────────────────────────────

  const handleDeleteLicense = async (lic: License) => {
    const confirmed = await confirm(
      destructiveConfirm({
        action: 'Delete',
        noun: 'license',
        name: lic.name,
        consequence:
          'Users holding this license lose the features it granted the next time they load the app.',
      })
    );
    if (!confirmed) return;
    const res = JSON.parse(await deleteLicense(lic.id));
    if (res.success) { showMessage('success', `License "${lic.name}" deleted`); loadAll(); }
    else showMessage('error', res.error);
  };

  // ── Feature flag tab ──────────────────────────────────────────────────────

  const handleDeleteFlag = async (ff: FeatureFlag) => {
    const confirmed = await confirm(
      destructiveConfirm({
        action: 'Delete',
        noun: 'feature flag',
        name: ff.label,
        consequence:
          'The flag is removed from every license and from every per-user override that named it.',
      })
    );
    if (!confirmed) return;
    const res = JSON.parse(await deleteFeatureFlag(ff.id));
    if (res.success) { showMessage('success', `Feature flag "${ff.label}" deleted`); loadAll(); }
    else showMessage('error', res.error);
  };

  const handleToggleFlag = async (ff: FeatureFlag) => {
    const res = JSON.parse(await updateFeatureFlag(ff.id, { enabled: !ff.enabled }));
    if (res.success) loadAll();
    else showMessage('error', res.error);
  };

  const handleDeletePackage = async (g: FeatureFlagGroup) => {
    const confirmed = await confirm(
      destructiveConfirm({
        action: 'Delete',
        noun: 'package',
        name: g.label,
        consequence:
          'The grouping goes; the flags inside it stay, and per-user overrides already granted are not changed.',
      })
    );
    if (!confirmed) return;
    const res = JSON.parse(await deleteFeatureFlagGroup(g.id));
    if (res.success) {
      showMessage('success', `Package "${g.label}" deleted`);
      loadAll();
    } else showMessage('error', res.error);
  };

  // ── Assignments tab ───────────────────────────────────────────────────────

  const handleAssignLicense = async (userId: string, licenseId: string) => {
    const res = JSON.parse(await assignLicenseToUser(userId, licenseId));
    if (res.success) { showMessage('success', 'License assigned'); setAssigningUser(null); loadAll(); }
    else showMessage('error', res.error);
  };

  const handleRemoveLicense = async (user: UserWithLicense) => {
    const confirmed = await confirm(
      destructiveConfirm({
        action: 'Remove',
        noun: 'license from',
        name: user.name,
        consequence:
          'They drop to the unlicensed feature set the next time they load the app. A license can be assigned again at any time.',
        confirmLabel: 'Remove license',
      })
    );
    if (!confirmed) return;
    const res = JSON.parse(await removeUserLicense(user.id));
    if (res.success) { showMessage('success', 'License removed'); loadAll(); }
    else showMessage('error', res.error);
  };

  const filteredUsers = usersWithLicenses.filter(u =>
    !assignSearch || u.name.toLowerCase().includes(assignSearch.toLowerCase()) ||
    u.email.toLowerCase().includes(assignSearch.toLowerCase())
  );

  // ─────────────────────────────────────────────────────────────────────────

  const TABS: { id: LicenseManagementTab; label: string; icon: React.ReactNode; count: number }[] = [
    { id: 'licenses',      label: 'Licenses',        icon: <Award className="w-4 h-4" />,    count: licenses.length },
    { id: 'featureFlags',  label: 'Feature Flags',   icon: <Flag className="w-4 h-4" />,     count: featureFlags.length },
    { id: 'flagPackages',  label: 'Flag packages',   icon: <Package className="w-4 h-4" />, count: flagGroups.length },
    { id: 'assignments',   label: 'Assignments',     icon: <Users className="w-4 h-4" />,   count: usersWithLicenses.filter(u => u.license_id).length },
  ];

  return (
    <>
      {/* Header */}
      <header className="shrink-0 border-b border-border bg-surface">
        <div className="px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-fg">Licenses</h2>
            <p className="text-fg-muted text-sm mt-1">
              Define license plans, feature flags, flag packages for bulk grants, and assign licenses to users
            </p>
          </div>
          <Button onClick={loadAll} disabled={loading} variant="outline">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </header>

      <main className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-subtle p-6">
        {/* Message banner */}
        {message && (
          <div className={`flex items-start gap-3 p-3 rounded-lg border text-sm ${message.type === 'success' ? 'bg-ok/20 border-ok text-ok-fg' : 'bg-danger/20 border-danger text-danger-fg'}`}>
            {message.type === 'success' ? <CheckCircle className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />}
            {message.text}
          </div>
        )}

        {/* Tabs */}
        <div className={TAB_LIST_CLASS} role="tablist" aria-label="License management views">
          {TABS.map(tab => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setActiveTab(tab.id)}
                className={tabTriggerClass({ active })}
              >
                {tab.icon}
                {tab.label}
                <span
                  className={`rounded-full px-1.5 py-0.5 text-xs ${
                    active
                      ? 'bg-accent-soft text-accent-fg'
                      : 'bg-inset text-fg-muted'
                  }`}
                >
                  {tab.count}
                </span>
              </button>
            );
          })}
        </div>

        {/* ── Licenses tab ─────────────────────────────────────────────────── */}
        {activeTab === 'licenses' && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <Button
                onClick={() => { setEditingLicense(null); setLicenseModal('create'); }}
                variant="accent"
              >
                <Plus className="w-4 h-4" /> New License
              </Button>
            </div>

            {loading ? (
              <LoadingState message="Loading license plans…" skeleton={<SkeletonCardGrid count={3} />} />
            ) : licenses.length === 0 ? (
              <EmptyState
                icon={<Award />}
                title="No license plans yet"
                description="Create a plan to grant feature flags to users."
              />
            ) : (
              <div className="space-y-2">
                {licenses.map(lic => (
                  <div key={lic.id} className="bg-surface border border-border rounded-xl overflow-hidden">
                    <div className="flex items-center gap-4 px-5 py-4">
                      <div className="p-2 bg-accent/20 rounded-lg">
                        <Award className="w-5 h-5 text-accent-fg" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-fg font-semibold">{lic.name}</span>
                          <Badge type={lic.license_type} />
                          {!lic.enabled && (
                            <span className="text-xs text-fg-muted italic">disabled</span>
                          )}
                        </div>
                        {lic.description && (
                          <p className="text-sm text-fg-muted truncate mt-0.5">{lic.description}</p>
                        )}
                        <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1">
                          {Object.entries(lic.seats).map(([k, v]) => (
                            <span key={k} className="text-xs text-fg-muted">
                              <span className="text-fg-muted font-mono">{k.replace(/_/g, ' ')}</span>: <span className="text-fg">{v}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={() => setExpandedLicenses(prev => {
                            const next = new Set(prev);
                            if (next.has(lic.id)) next.delete(lic.id); else next.add(lic.id);
                            return next;
                          })}
                          className="p-2 text-fg-muted hover:text-fg-muted rounded-lg hover:bg-subtle transition-colors"
                          title="Toggle feature flags"
                        >
                          {expandedLicenses.has(lic.id) ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                        </button>
                        <button
                          onClick={() => { setEditingLicense(lic); setLicenseModal('edit'); }}
                          className="p-2 text-fg-muted hover:text-fg-muted rounded-lg hover:bg-subtle transition-colors"
                          title="Edit"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDeleteLicense(lic)}
                          className="p-2 text-fg-muted hover:text-danger-fg rounded-lg hover:bg-subtle transition-colors"
                          title="Delete"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>

                    {expandedLicenses.has(lic.id) && (
                      <div className="border-t border-border bg-subtle px-5 py-3">
                        <p className="text-xs font-medium text-fg-muted uppercase tracking-wide mb-2">Included Feature Flags</p>
                        {lic.feature_flags.length === 0 ? (
                          <p className="text-xs text-fg-muted italic">No feature flags assigned to this license.</p>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            {lic.feature_flags.map(ff => (
                              <span key={ff.id} className="flex items-center gap-1.5 px-2.5 py-1 bg-subtle border border-border-strong rounded-full text-xs text-fg-muted">
                                <Flag className="w-3 h-3 text-accent-fg" />
                                {ff.label}
                                {ff.is_preview && <PreviewBadge />}
                              </span>
                            ))}
                          </div>
                        )}

                        <p className="text-xs font-medium text-fg-muted uppercase tracking-wide mt-3 mb-1.5">
                          Seat limits
                        </p>
                        <dl className="grid gap-1.5 sm:grid-cols-2">
                          {Object.entries(lic.seats).map(([k, v]) => (
                            <div
                              key={k}
                              className="flex items-baseline justify-between gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5"
                            >
                              <dt className="font-mono text-2xs text-fg-muted">{k}</dt>
                              <dd className="text-sm font-semibold tabular-nums text-fg">{v}</dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Feature Flags tab ─────────────────────────────────────────────── */}
        {activeTab === 'featureFlags' && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <Button
                onClick={() => { setEditingFlag(null); setFlagModal('create'); }}
                variant="accent"
              >
                <Plus className="w-4 h-4" /> New Feature Flag
              </Button>
            </div>

            {loading ? (
              <LoadingState message="Loading feature flags…" skeleton={<SkeletonCardGrid count={3} />} />
            ) : featureFlags.length === 0 ? (
              <EmptyState
                icon={<Flag />}
                title="No feature flags yet"
                description="Flags gate features per license or per user."
                action={
                  <Button
                    variant="primary"
                    onClick={() => { setEditingFlag(null); setFlagModal('create'); }}
                  >
                    <Plus aria-hidden /> New feature flag
                  </Button>
                }
              />
            ) : (
              <div className="space-y-2">
                {featureFlags.map(ff => (
                  <div key={ff.id} className="bg-surface border border-border rounded-xl px-5 py-4 flex items-start gap-4">
                    <div className="p-2 bg-violet/20 rounded-lg mt-0.5 shrink-0">
                      <Flag className="w-4 h-4 text-violet-fg" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-fg font-semibold">{ff.label}</span>
                        <code className="rounded-xs bg-inset px-1.5 py-0.5 font-mono text-xs text-fg-muted">
                          {ff.name}
                        </code>
                        {ff.is_preview && <PreviewBadge />}
                        {!ff.enabled && <span className="text-xs text-fg-muted italic">disabled</span>}
                      </div>
                      {ff.description && (
                        <p className="text-sm text-fg-muted mt-0.5">{ff.description}</p>
                      )}
                      {ff.url_patterns.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {ff.url_patterns.map((p, i) => (
                            <span
                              key={i}
                              className="flex items-center gap-1 rounded-xs border border-border-strong bg-subtle px-2 py-0.5 font-mono text-xs text-ok-fg"
                            >
                              <Link className="h-2.5 w-2.5 text-fg-muted" />
                              {p}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => handleToggleFlag(ff)}
                        className={`p-2 rounded-lg hover:bg-subtle transition-colors ${ff.enabled ? 'text-ok-fg' : 'text-fg-muted'}`}
                        title={ff.enabled ? 'Disable' : 'Enable'}
                      >
                        {ff.enabled ? <ToggleRight className="w-5 h-5" /> : <ToggleLeft className="w-5 h-5" />}
                      </button>
                      <button
                        onClick={() => { setEditingFlag(ff); setFlagModal('edit'); }}
                        className="p-2 text-fg-muted hover:text-fg-muted rounded-lg hover:bg-subtle transition-colors"
                        title="Edit"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDeleteFlag(ff)}
                        className="p-2 text-fg-muted hover:text-danger-fg rounded-lg hover:bg-subtle transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Flag packages tab ─────────────────────────────────────────────── */}
        {activeTab === 'flagPackages' && (
          <div className="space-y-3">
            <div className="flex justify-end">
              <Button
                onClick={() => {
                  setEditingPackage(null);
                  setPackageModal('create');
                }}
                variant="accent"
              >
                <Plus className="w-4 h-4" /> New flag package
              </Button>
            </div>

            {loading ? (
              <LoadingState message="Loading flag packages…" skeleton={<SkeletonCardGrid count={3} />} />
            ) : flagGroups.length === 0 ? (
              <EmptyState
                icon={<Package />}
                title="No flag packages yet"
                description="Group several feature flags to grant them to users at once."
              />
            ) : (
              <div className="space-y-2">
                {flagGroups.map(g => (
                  <div
                    key={g.id}
                    className="bg-surface border border-border rounded-xl px-5 py-4 flex items-start gap-4"
                  >
                    <div className="p-2 bg-accent/20 rounded-lg mt-0.5 shrink-0">
                      <Package className="w-4 h-4 text-accent-fg" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-fg font-semibold">{g.label}</span>
                        <code className="rounded-xs bg-inset px-1.5 py-0.5 font-mono text-xs text-fg-muted">
                          {g.name}
                        </code>
                      </div>
                      {g.description && (
                        <p className="text-sm text-fg-muted mt-0.5">{g.description}</p>
                      )}
                      {g.feature_flags.length === 0 ? (
                        <p className="text-xs text-fg-muted italic mt-2">No flags in this package yet.</p>
                      ) : (
                        <div className="flex flex-wrap gap-2 mt-2">
                          {g.feature_flags.map(ff => (
                            <span
                              key={ff.id}
                              className="flex items-center gap-1.5 px-2.5 py-1 bg-subtle border border-border-strong rounded-full text-xs text-fg-muted"
                            >
                              <Flag className="w-3 h-3 text-accent-fg" />
                              {ff.label}
                              {ff.is_preview && <PreviewBadge />}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => {
                          setEditingPackage(g);
                          setPackageModal('edit');
                        }}
                        className="p-2 text-fg-muted hover:text-fg-muted rounded-lg hover:bg-subtle transition-colors"
                        title="Edit"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDeletePackage(g)}
                        className="p-2 text-fg-muted hover:text-danger-fg rounded-lg hover:bg-subtle transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Assignments tab ───────────────────────────────────────────────── */}
        {activeTab === 'assignments' && (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <Input
                type="text"
                placeholder="Search users…"
                value={assignSearch}
                onChange={e => setAssignSearch(e.target.value)}
                className="flex-1"
              />
              <span className="text-xs text-fg-muted shrink-0">{filteredUsers.length} user{filteredUsers.length !== 1 ? 's' : ''}</span>
            </div>

            {loading ? (
              <LoadingState message="Loading users…" skeleton={<SkeletonText lines={6} />} />
            ) : (
              <div className="overflow-x-auto rounded-xl border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-subtle text-left text-xs text-fg-muted uppercase tracking-wide">
                      <th className="px-4 py-3 font-medium">User</th>
                      <th className="px-4 py-3 font-medium">Assigned License</th>
                      <th className="px-4 py-3 font-medium">Seats</th>
                      <th className="px-4 py-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {filteredUsers.map(user => (
                      <tr key={user.id} className="bg-surface hover:bg-subtle transition-colors">
                        <td className="px-4 py-3">
                          <div className="font-medium text-fg">{user.name}</div>
                          <div className="text-xs text-fg-muted">{user.email}</div>
                        </td>
                        <td className="px-4 py-3">
                          {user.license_name ? (
                            <div className="flex items-center gap-2">
                              <Badge type={user.license_type!} />
                              <span className="text-fg">{user.license_name}</span>
                            </div>
                          ) : (
                            <span className="text-fg-muted italic text-xs">No license</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {user.seats ? (
                            <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                              {Object.entries(user.seats).map(([k, v]) => (
                                <span key={k} className="text-xs text-fg-muted">
                                  {k.replace(/_/g, ' ')}: <span className="text-fg">{v}</span>
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-fg-muted text-xs">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              onClick={() => setAssigningUser(user)}
                              variant="accent" size="sm" className="text-xs text-accent-fg border-accent/60"
                            >
                              <ShieldCheck className="w-3.5 h-3.5" />
                              Assign
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </main>

      {/* ── License Modal ──────────────────────────────────────────────────── */}
      {licenseModal && (
        <Modal
          fixedViewportHeight
          title={licenseModal === 'create' ? 'New License Plan' : `Edit — ${editingLicense?.name}`}
          onClose={() => setLicenseModal(null)}
        >
          <LicenseForm
            existing={licenseModal === 'edit' ? editingLicense : null}
            allFlags={featureFlags}
            onSave={() => { setLicenseModal(null); loadAll(); showMessage('success', 'License saved'); }}
            onCancel={() => setLicenseModal(null)}
          />
        </Modal>
      )}

      {/* ── Feature Flag Modal ─────────────────────────────────────────────── */}
      {flagModal && (
        <Modal
          title={flagModal === 'create' ? 'New Feature Flag' : `Edit — ${editingFlag?.label}`}
          onClose={() => setFlagModal(null)}
        >
          <FlagForm
            existing={flagModal === 'edit' ? editingFlag : null}
            onSave={() => { setFlagModal(null); loadAll(); showMessage('success', 'Feature flag saved'); }}
            onCancel={() => setFlagModal(null)}
          />
        </Modal>
      )}

      {packageModal && (
        <Modal
          title={packageModal === 'create' ? 'New flag package' : `Edit package — ${editingPackage?.label}`}
          onClose={() => setPackageModal(null)}
        >
          <FlagPackageForm
            existing={packageModal === 'edit' ? editingPackage : null}
            allFlags={featureFlags}
            onSave={() => {
              setPackageModal(null);
              loadAll();
              showMessage('success', 'Flag package saved');
            }}
            onCancel={() => setPackageModal(null)}
          />
        </Modal>
      )}

      {/* ── Assign license Modal ───────────────────────────────────────────── */}
      {assigningUser && (
        <Modal
          title={`Assign license — ${assigningUser.name}`}
          onClose={() => setAssigningUser(null)}
          panelClassName="max-w-md"
        >
          <p className="mb-4 text-sm text-fg-muted">{assigningUser.email}</p>
          <div className="space-y-1">
            {licenses.filter((lic) => lic.enabled).map((lic) => (
              <button
                key={lic.id}
                type="button"
                onClick={() => handleAssignLicense(assigningUser.id, lic.id)}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm text-fg transition-colors hover:bg-subtle"
              >
                <Badge type={lic.license_type} />
                <span className="flex-1">{lic.name}</span>
                {lic.id === assigningUser.license_id && (
                  <CheckCircle className="ml-auto h-4 w-4 shrink-0 text-ok-fg" />
                )}
              </button>
            ))}
          </div>
          <div className="mt-4 space-y-1 border-t border-border pt-3">
            <button
              type="button"
              onClick={() => {
                setOverrideUser(assigningUser);
                setAssigningUser(null);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm text-accent-fg transition-colors hover:bg-subtle"
            >
              <Flag className="h-4 w-4" />
              Override feature flags…
            </button>
            {assigningUser.license_id && (
              <button
                type="button"
                onClick={() => {
                  handleRemoveLicense(assigningUser);
                  setAssigningUser(null);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm text-danger-fg transition-colors hover:bg-subtle"
              >
                <Trash2 className="h-4 w-4" />
                Remove license
              </button>
            )}
          </div>
        </Modal>
      )}

      {/* ── Per-user flag override Modal ───────────────────────────────────── */}
      {overrideUser && (
        <Modal
          fixedViewportHeight
          title={`Feature flags — ${overrideUser.name}`}
          onClose={() => {
            setOverrideUser(null);
            loadAll();
          }}
        >
          <FeatureFlagUserOverridesPanel
            className="h-full min-h-0"
            userId={overrideUser.id}
            userName={overrideUser.name}
            userEmail={overrideUser.email}
            onNotify={showMessage}
          />
        </Modal>
      )}

    </>
  );
}

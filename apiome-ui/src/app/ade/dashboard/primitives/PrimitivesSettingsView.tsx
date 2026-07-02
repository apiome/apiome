'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Database,
  CheckCircle2,
  AlertTriangle,
  Save,
  RotateCcw,
  FileJson,
  GitFork,
  Upload,
  ShieldCheck,
} from 'lucide-react';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { LoadingState } from '@/app/components/ui/LoadingState';
import {
  dashboardPanelClass,
  dashboardPanelPaddedClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  ACCEPTED_FORMAT_OPTIONS,
  CIRCULAR_POLICY_OPTIONS,
  CORE_PUBLISH_ROLE_OPTIONS,
  DEFAULT_SETTINGS,
  DRAFT_OPTIONS,
  IMPORT_SCOPE_OPTIONS,
  MAX_RESOLUTION_DEPTH,
  MIN_RESOLUTION_DEPTH,
  REF_STYLE_OPTIONS,
  clampDepth,
  coerceSettings,
  diffSettings,
  formatAllowlist,
  hasChanges,
  parseAllowlist,
  toggleInList,
  type CircularRefPolicy,
  type CorePublishRole,
  type DefaultDraft,
  type ImportScope,
  type RefStyle,
  type RegistryHealth,
  type TypeRegistrySettings,
  type TypeRegistrySettingsResponse,
} from './primitivesSettingsModel';

interface PrimitivesSettingsViewProps {
  /** Surface success/error notices through the parent screen's alert. */
  onMessage?: (type: 'success' | 'error', text: string) => void;
}

/** Shared classes for the section <select> controls (CSS-only, no inline values). */
const selectClass =
  'w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-white';
const sectionTitleClass =
  'flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white';
const fieldLabelClass = 'block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1';
const helpTextClass = 'text-xs text-gray-400 mt-1';

/** A labelled checkbox toggle with a short description, used throughout the form. */
function ToggleRow({
  id,
  label,
  description,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label htmlFor={id} className="flex items-start gap-3 cursor-pointer py-1.5">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 w-4 h-4 text-indigo-600 rounded"
      />
      <span className="min-w-0">
        <span className="block text-sm text-gray-800 dark:text-gray-200">{label}</span>
        <span className="block text-xs text-gray-400">{description}</span>
      </span>
    </label>
  );
}

/** A titled settings card wrapping a group of related controls. */
function SettingsSection({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className={dashboardPanelPaddedClass}>
      <h3 className={sectionTitleClass}>
        {icon}
        {title}
      </h3>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

/**
 * Type Registry Settings view (#3472).
 *
 * Renders the registry storage status (live, from `GET /api/primitives/health`) plus the
 * editable registry settings (`GET`/`PUT /api/types/settings`): JSON Schema dialect, `$ref`
 * resolution policy, import defaults, and validation/publishing governance. Saving sends only
 * the changed fields; the persisted settings become the source of truth the resolver and the
 * validation gate (#3479) read. There is no separate registry database — storage is the shared
 * `apiome-db` (single-DB design), which the status section makes explicit.
 */
export default function PrimitivesSettingsView({ onMessage }: PrimitivesSettingsViewProps) {
  // `baseline` is the last-saved state; `form` is the in-progress edit. Save diffs the two.
  const [baseline, setBaseline] = useState<TypeRegistrySettings>(DEFAULT_SETTINGS);
  const [form, setForm] = useState<TypeRegistrySettings>(DEFAULT_SETTINGS);
  const [usingDefaults, setUsingDefaults] = useState(true);
  const [health, setHealth] = useState<RegistryHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // The allowlist textarea is edited as free text and parsed into the form on change.
  const [allowlistText, setAllowlistText] = useState(
    formatAllowlist(DEFAULT_SETTINGS.remote_host_allowlist)
  );

  const applyLoaded = useCallback((settings: TypeRegistrySettings) => {
    setBaseline(settings);
    setForm(settings);
    setAllowlistText(formatAllowlist(settings.remote_host_allowlist));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [settingsRes, healthRes] = await Promise.all([
        fetch('/api/types/settings'),
        fetch('/api/primitives/health'),
      ]);
      const [settingsData, healthData] = await Promise.all([
        settingsRes.json(),
        healthRes.json(),
      ]);

      if (settingsData.success && settingsData.settings) {
        const payload = settingsData.settings as TypeRegistrySettingsResponse;
        setUsingDefaults(Boolean(payload.is_default));
        applyLoaded(coerceSettings(payload));
      } else {
        onMessage?.('error', settingsData.error || 'Failed to load settings');
      }

      if (healthData.success && healthData.health) {
        setHealth(healthData.health as RegistryHealth);
      } else {
        setHealth(null);
      }
    } catch (error) {
      console.error('Error loading registry settings:', error);
      onMessage?.('error', 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  }, [applyLoaded, onMessage]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(() => hasChanges(baseline, form), [baseline, form]);

  /** Patch one field of the in-progress form. */
  const setField = useCallback(
    <K extends keyof TypeRegistrySettings>(key: K, value: TypeRegistrySettings[K]) => {
      setForm((current) => ({ ...current, [key]: value }));
    },
    []
  );

  const handleAllowlistChange = useCallback((text: string) => {
    setAllowlistText(text);
    setForm((current) => ({ ...current, remote_host_allowlist: parseAllowlist(text) }));
  }, []);

  const handleReset = useCallback(() => {
    setForm(DEFAULT_SETTINGS);
    setAllowlistText(formatAllowlist(DEFAULT_SETTINGS.remote_host_allowlist));
  }, []);

  const handleSave = useCallback(async () => {
    const payload = diffSettings(baseline, form);
    if (Object.keys(payload).length === 0) {
      onMessage?.('error', 'No changes to save');
      return;
    }

    setSaving(true);
    try {
      const res = await fetch('/api/types/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.success && data.settings) {
        const saved = data.settings as TypeRegistrySettingsResponse;
        setUsingDefaults(Boolean(saved.is_default));
        applyLoaded(coerceSettings(saved));
        onMessage?.('success', 'Registry settings saved');
      } else {
        onMessage?.('error', data.error || 'Failed to save settings');
      }
    } catch (error) {
      console.error('Error saving registry settings:', error);
      onMessage?.('error', 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  }, [applyLoaded, baseline, form, onMessage]);

  if (loading) {
    return <LoadingState minHeightClassName="min-h-[320px]" message="Loading settings…" />;
  }

  const connected = health?.connection === 'connected' && health?.status === 'healthy';

  return (
    <div className="space-y-6">
      {usingDefaults && (
        <div className="flex items-center gap-2 text-xs text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-200 dark:border-indigo-800 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
          <span>
            This tenant is using the registry defaults. Save to persist a tenant-specific
            configuration.
          </span>
        </div>
      )}

      {/* Registry storage status — live from the registry health probe (#3450). */}
      <section className={dashboardPanelPaddedClass}>
        <div className="flex items-center justify-between gap-4">
          <h3 className={sectionTitleClass}>
            <Database className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
            Registry storage
          </h3>
          {health ? (
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                connected
                  ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                  : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
              }`}
            >
              {connected ? (
                <CheckCircle2 className="w-3.5 h-3.5" />
              ) : (
                <AlertTriangle className="w-3.5 h-3.5" />
              )}
              {connected ? 'Connected' : 'Unavailable'}
            </span>
          ) : (
            <span className="text-xs text-gray-400">status unknown</span>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
          The registry is stored in the shared <span className="font-mono">apiome-db</span>{' '}
          (<span className="font-mono">apiome.primitives</span>) — there is no separate registry
          database. Storage table present:{' '}
          <span className="font-mono">{health?.storage_present ? 'yes' : 'no'}</span>.
        </p>
        {health?.error && (
          <p className="text-xs text-red-600 dark:text-red-400 mt-1 font-mono">{health.error}</p>
        )}
      </section>

      {/* JSON Schema dialect */}
      <SettingsSection
        icon={<FileJson className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />}
        title="JSON Schema dialect"
      >
        <div>
          <label htmlFor="default-draft" className={fieldLabelClass}>
            Default draft
          </label>
          <select
            id="default-draft"
            value={form.default_draft}
            onChange={(e) => setField('default_draft', e.target.value as DefaultDraft)}
            className={selectClass}
          >
            {DRAFT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <ToggleRow
          id="strict-validation"
          label="Strict validation"
          description="Reject unknown formats."
          checked={form.strict_validation}
          onChange={(value) => setField('strict_validation', value)}
        />
        <ToggleRow
          id="allow-annotations"
          label="Allow annotation keywords"
          description="Permit title, description, examples, etc."
          checked={form.allow_annotation_keywords}
          onChange={(value) => setField('allow_annotation_keywords', value)}
        />
        <ToggleRow
          id="coerce-drafts"
          label="Coerce imported drafts to default"
          description="Upgrade older drafts to the default dialect on import."
          checked={form.coerce_imported_drafts}
          onChange={(value) => setField('coerce_imported_drafts', value)}
        />
      </SettingsSection>

      {/* Reference resolution */}
      <SettingsSection
        icon={<GitFork className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />}
        title="Reference resolution"
      >
        <div>
          <label htmlFor="resolution-base" className={fieldLabelClass}>
            Resolution base URL
          </label>
          <Input
            id="resolution-base"
            type="text"
            value={form.resolution_base_url}
            onChange={(e) => setField('resolution_base_url', e.target.value)}
          />
          <p className={helpTextClass}>Relative $ref resolve against this base.</p>
        </div>
        <div>
          <label htmlFor="ref-style" className={fieldLabelClass}>
            $ref style
          </label>
          <select
            id="ref-style"
            value={form.ref_style}
            onChange={(e) => setField('ref_style', e.target.value as RefStyle)}
            className={selectClass}
          >
            {REF_STYLE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <ToggleRow
          id="allow-remote-refs"
          label="Allow remote $ref"
          description="Fetch schemas from external hosts during resolution."
          checked={form.allow_remote_refs}
          onChange={(value) => setField('allow_remote_refs', value)}
        />
        <div>
          <label htmlFor="remote-allowlist" className={fieldLabelClass}>
            Remote host allowlist
          </label>
          <textarea
            id="remote-allowlist"
            value={allowlistText}
            onChange={(e) => handleAllowlistChange(e.target.value)}
            disabled={!form.allow_remote_refs}
            rows={3}
            placeholder="json-schema.org&#10;spec.openapis.org"
            className={`${selectClass} font-mono disabled:opacity-50 disabled:cursor-not-allowed`}
          />
          <p className={helpTextClass}>One host per line. Only used when remote $ref is allowed.</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="max-depth" className={fieldLabelClass}>
              Max resolution depth
            </label>
            <Input
              id="max-depth"
              type="number"
              min={MIN_RESOLUTION_DEPTH}
              max={MAX_RESOLUTION_DEPTH}
              value={form.max_resolution_depth}
              onChange={(e) => setField('max_resolution_depth', clampDepth(Number(e.target.value)))}
            />
          </div>
          <div>
            <label htmlFor="circular-policy" className={fieldLabelClass}>
              Circular ref policy
            </label>
            <select
              id="circular-policy"
              value={form.circular_ref_policy}
              onChange={(e) => setField('circular_ref_policy', e.target.value as CircularRefPolicy)}
              className={selectClass}
            >
              {CIRCULAR_POLICY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </SettingsSection>

      {/* Import defaults */}
      <SettingsSection
        icon={<Upload className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />}
        title="Import defaults"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="import-scope" className={fieldLabelClass}>
              Default scope
            </label>
            <select
              id="import-scope"
              value={form.default_import_scope}
              onChange={(e) => setField('default_import_scope', e.target.value as ImportScope)}
              className={selectClass}
            >
              {IMPORT_SCOPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="default-namespace" className={fieldLabelClass}>
              Default target namespace
            </label>
            <Input
              id="default-namespace"
              type="text"
              value={form.default_target_namespace ?? ''}
              placeholder="(none)"
              onChange={(e) =>
                setField('default_target_namespace', e.target.value.trim() ? e.target.value : null)
              }
            />
          </div>
        </div>
        <ToggleRow
          id="rewrite-refs"
          label="Rewrite refs to relative on import"
          description="Convert absolute $ref to base-relative paths."
          checked={form.rewrite_refs_on_import}
          onChange={(value) => setField('rewrite_refs_on_import', value)}
        />
        <div>
          <span className={fieldLabelClass}>Accepted formats</span>
          <div className="space-y-1">
            {ACCEPTED_FORMAT_OPTIONS.map((option) => {
              const id = `format-${option.value}`;
              return (
                <label key={option.value} htmlFor={id} className="flex items-center gap-2 cursor-pointer">
                  <input
                    id={id}
                    type="checkbox"
                    checked={form.accepted_formats.includes(option.value)}
                    onChange={() =>
                      setField('accepted_formats', toggleInList(form.accepted_formats, option.value))
                    }
                    className="w-4 h-4 text-indigo-600 rounded"
                  />
                  <span className="text-sm text-gray-800 dark:text-gray-200">{option.label}</span>
                </label>
              );
            })}
          </div>
        </div>
        <ToggleRow
          id="dedupe-types"
          label="Dedupe identical types"
          description="Reuse an existing type when an import matches it byte-for-byte."
          checked={form.dedupe_identical_types}
          onChange={(value) => setField('dedupe_identical_types', value)}
        />
      </SettingsSection>

      {/* Validation & publishing */}
      <SettingsSection
        icon={<ShieldCheck className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />}
        title="Validation & publishing"
      >
        <ToggleRow
          id="validate-on-save"
          label="Validate on save"
          description="Run dialect & $ref checks before persisting."
          checked={form.validate_on_save}
          onChange={(value) => setField('validate_on_save', value)}
        />
        <ToggleRow
          id="block-publish"
          label="Block publish on validation errors"
          description="Prevent publishing types with unresolved $ref or schema errors."
          checked={form.block_publish_on_errors}
          onChange={(value) => setField('block_publish_on_errors', value)}
        />
        <div>
          <label htmlFor="core-publish-role" className={fieldLabelClass}>
            Who can publish core (std/*) types
          </label>
          <select
            id="core-publish-role"
            value={form.core_publish_role}
            onChange={(e) => setField('core_publish_role', e.target.value as CorePublishRole)}
            className={selectClass}
          >
            {CORE_PUBLISH_ROLE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className={helpTextClass}>
            Core system types are shared with all tenants; publishing is governed.
          </p>
        </div>
      </SettingsSection>

      {/* Footer actions */}
      <div className={`${dashboardPanelClass} p-4 flex items-center justify-between gap-4`}>
        <Button variant="secondary" onClick={handleReset} disabled={saving}>
          <RotateCcw className="w-4 h-4 mr-2" />
          Reset to defaults
        </Button>
        <Button onClick={handleSave} disabled={saving || !dirty}>
          <Save className="w-4 h-4 mr-2" />
          {saving ? 'Saving…' : 'Save settings'}
        </Button>
      </div>
    </div>
  );
}

'use client';

/**
 * Per-key MCP capability editor — MTG-4.3 (#4782).
 *
 * Lists MCP API keys, lets admins choose Inherit vs Custom, and when Custom
 * exposes toolset toggles constrained by the saved tenant ceiling. Effective
 * summary comes from MTG-3.3 capabilities/preview.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BadgeCheck, KeyRound, Loader2, Lock } from 'lucide-react';
import { toast } from 'sonner';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Label } from '@/app/components/ui/Label';
import { RadioGroup, RadioGroupItem } from '@/app/components/ui/RadioGroup';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { Switch } from '@/app/components/ui/Switch';
import type { McpToolCatalogItem } from './mcpPolicyApi';
import {
  fetchMcpKeys,
  previewMcpKeyCapabilities,
  putMcpKeyCapabilities,
  type McpApiKeyMetadata,
  type McpKeyCapabilityMode,
  type McpKeyEffectiveToolRow,
} from './mcpKeysApi';
import {
  buildMcpKeyCapabilitiesPutBody,
  groupKeyToolsByToolset,
  hasMcpKeyCapabilityChanges,
  mcpKeyCapabilityFormFromSources,
  patchKeyToolEnabled,
  patchKeyToolsetEnabled,
  setKeyCapabilityMode,
  validateMcpKeyCapabilityForm,
  type McpKeyCapabilityFormState,
} from './mcpKeyCapabilityForm';

export interface TenantMcpKeyCapabilitiesEditorProps {
  /** Catalog tools (id / description / toolset). */
  catalog: McpToolCatalogItem[];
  /** Tool ids in the saved tenant ceiling (baseline, not dirty form). */
  ceilingToolIds: string[];
  /**
   * Bumped when tenant policy is saved so inherit previews refresh against
   * the new default enable-set.
   */
  policyRevision: number;
}

const EMPTY_KEYS_COPY = 'No MCP API keys yet for this tenant.';

function titleCaseToolset(toolset: string): string {
  if (!toolset) return 'Other';
  return toolset.charAt(0).toUpperCase() + toolset.slice(1);
}

function keyOptionLabel(key: McpApiKeyMetadata): string {
  const revoked = key.revoked_at ? ' (revoked)' : '';
  return `${key.label} · ${key.prefix}…${revoked}`;
}

export default function TenantMcpKeyCapabilitiesEditor({
  catalog,
  ceilingToolIds,
  policyRevision,
}: TenantMcpKeyCapabilitiesEditorProps) {
  const [keys, setKeys] = useState<McpApiKeyMetadata[]>([]);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysError, setKeysError] = useState<string | null>(null);
  const [selectedKeyId, setSelectedKeyId] = useState<string | null>(null);
  const [form, setForm] = useState<McpKeyCapabilityFormState | null>(null);
  const [baseline, setBaseline] = useState<McpKeyCapabilityFormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewRows, setPreviewRows] = useState<McpKeyEffectiveToolRow[] | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadKeys = useCallback(async () => {
    setKeysLoading(true);
    setKeysError(null);
    try {
      const list = await fetchMcpKeys();
      const all = list.keys ?? [];
      setKeys(all);
      const firstActive = all.find((k) => !k.revoked_at) ?? all[0] ?? null;
      setSelectedKeyId((prev) => {
        if (prev && all.some((k) => k.id === prev)) return prev;
        return firstActive?.id ?? null;
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load MCP keys';
      setKeysError(message);
    } finally {
      setKeysLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  const selectedKey = useMemo(
    () => keys.find((k) => k.id === selectedKeyId) ?? null,
    [keys, selectedKeyId],
  );

  useEffect(() => {
    if (!selectedKey) {
      setForm(null);
      setBaseline(null);
      setPreviewRows(null);
      return;
    }
    const next = mcpKeyCapabilityFormFromSources(
      selectedKey.capability_mode,
      selectedKey.enabled_tools ?? [],
      catalog,
      ceilingToolIds,
    );
    setForm(next);
    setBaseline(next);
    setError(null);
  }, [selectedKey, catalog, ceilingToolIds]);

  const dirty = form && baseline ? hasMcpKeyCapabilityChanges(form, baseline) : false;
  const toolsetGroups = useMemo(
    () => (form ? groupKeyToolsByToolset(form.tools) : []),
    [form],
  );

  const schedulePreview = useCallback(
    (keyId: string, state: McpKeyCapabilityFormState) => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
      previewTimer.current = setTimeout(async () => {
        setPreviewLoading(true);
        try {
          const body = buildMcpKeyCapabilitiesPutBody(state);
          const result = await previewMcpKeyCapabilities(keyId, body);
          setPreviewRows(result.tools ?? []);
        } catch {
          setPreviewRows(null);
        } finally {
          setPreviewLoading(false);
        }
      }, 250);
    },
    [],
  );

  useEffect(() => {
    if (!selectedKeyId || !form) return;
    schedulePreview(selectedKeyId, form);
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
    };
  }, [selectedKeyId, form, policyRevision, schedulePreview]);

  const handleDiscard = () => {
    if (baseline) setForm(baseline);
    setError(null);
  };

  const handleModeChange = (value: string) => {
    const mode = value as McpKeyCapabilityMode;
    setForm((prev) => (prev ? setKeyCapabilityMode(prev, mode) : prev));
  };

  const handleSave = async () => {
    if (!form || !selectedKeyId) return;
    const validation = validateMcpKeyCapabilityForm(form);
    if (validation) {
      setError(validation);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = buildMcpKeyCapabilitiesPutBody(form);
      const saved = await putMcpKeyCapabilities(selectedKeyId, body);
      const next = mcpKeyCapabilityFormFromSources(
        saved.mode,
        saved.enabled_tools ?? [],
        catalog,
        ceilingToolIds,
      );
      setForm(next);
      setBaseline(next);
      setKeys((prev) =>
        prev.map((k) =>
          k.id === selectedKeyId
            ? {
                ...k,
                capability_mode: saved.mode,
                enabled_tools: saved.enabled_tools ?? [],
              }
            : k,
        ),
      );
      toast.success('MCP key capabilities saved');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save capabilities';
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  const enabledPreview = useMemo(
    () => (previewRows ?? []).filter((row) => row.enabled).map((row) => row.tool_id),
    [previewRows],
  );
  const deniedCount = (previewRows ?? []).filter((row) => !row.enabled).length;

  if (keysLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 py-2">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading MCP keys…
      </div>
    );
  }

  if (keysError) {
    return <Alert variant="error">{keysError}</Alert>;
  }

  if (keys.length === 0) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 py-2">{EMPTY_KEYS_COPY}</p>
    );
  }

  return (
    <div className="space-y-4 border-t border-slate-200 pt-4 dark:border-slate-800">
      <div className="flex items-center gap-2">
        <div className="p-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-900/30">
          <KeyRound className="h-4 w-4 text-indigo-600 dark:text-indigo-400" aria-hidden />
        </div>
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
          Per-key capabilities
        </h3>
      </div>

      <p className="text-sm text-gray-500 dark:text-gray-400">
        Effective call access is per MCP API key. Inherit follows tenant defaults;
        Custom sets an enable-set capped by the ceiling above.
      </p>

      {error && <Alert variant="error">{error}</Alert>}

      <div className="space-y-2">
        <Label htmlFor="mcp-key-select">MCP API key</Label>
        <Select
          value={selectedKeyId ?? undefined}
          onValueChange={(id) => setSelectedKeyId(id)}
          disabled={saving}
        >
          <SelectTrigger id="mcp-key-select" aria-label="Select MCP API key">
            <SelectValue placeholder="Select a key" />
          </SelectTrigger>
          <SelectContent>
            {keys.map((key) => (
              <SelectItem key={key.id} value={key.id} disabled={Boolean(key.revoked_at)}>
                {keyOptionLabel(key)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {form && (
        <>
          <div className="space-y-2">
            <Label>Capability mode</Label>
            <RadioGroup
              value={form.mode}
              onValueChange={handleModeChange}
              aria-label="Capability mode"
            >
              <RadioGroupItem
                value="inherit"
                label="Inherit tenant defaults"
                disabled={saving || Boolean(selectedKey?.revoked_at)}
              />
              <RadioGroupItem
                value="explicit"
                label="Custom enable-set"
                disabled={saving || Boolean(selectedKey?.revoked_at)}
              />
            </RadioGroup>
          </div>

          <div className="space-y-3">
            <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Toolsets
              {form.mode === 'inherit' ? (
                <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                  (read-only while inheriting)
                </span>
              ) : null}
            </h4>

            {toolsetGroups.length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                No MCP tools in the registry catalog.
              </p>
            ) : (
              <div className="space-y-3">
                {toolsetGroups.map((group) => {
                  const allLocked = group.unlockedCount === 0;
                  const switchDisabled =
                    saving ||
                    form.mode === 'inherit' ||
                    Boolean(selectedKey?.revoked_at) ||
                    allLocked;
                  return (
                    <section
                      key={group.toolset}
                      aria-label={`${group.toolset} key toolset`}
                      className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
                    >
                      <div className="flex items-center gap-4 border-b border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/50">
                        <Switch
                          aria-label={`Enable ${group.toolset} for key`}
                          checked={group.enableState === 'all'}
                          indeterminate={group.enableState === 'mixed'}
                          onCheckedChange={(checked) =>
                            setForm((prev) =>
                              prev
                                ? patchKeyToolsetEnabled(prev, group.toolset, checked)
                                : prev,
                            )
                          }
                          disabled={switchDisabled}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-semibold text-gray-900 dark:text-white">
                            {titleCaseToolset(group.toolset)}
                          </div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">
                            {group.enabledUnlockedCount} of {group.unlockedCount} unlocked
                            tools enabled
                            {allLocked ? ' · all tools locked by ceiling' : ''}
                          </div>
                        </div>
                        {allLocked ? (
                          <Lock
                            className="h-4 w-4 text-slate-400"
                            aria-label="Toolset locked by ceiling"
                          />
                        ) : null}
                      </div>
                      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                        {group.tools.map((tool) => {
                          const locked = !tool.in_ceiling;
                          return (
                            <li
                              key={tool.tool_id}
                              className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-white">
                                  {tool.tool_id}
                                  {locked ? (
                                    <Lock
                                      className="h-3.5 w-3.5 text-slate-400"
                                      aria-label={`${tool.tool_id} locked by ceiling`}
                                    />
                                  ) : null}
                                </div>
                                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                  {locked
                                    ? 'Outside tenant ceiling — cannot enable for this key'
                                    : tool.description}
                                </div>
                              </div>
                              <Switch
                                aria-label={`${tool.tool_id} enabled for key`}
                                checked={tool.enabled}
                                onCheckedChange={(checked) =>
                                  setForm((prev) =>
                                    prev
                                      ? patchKeyToolEnabled(prev, tool.tool_id, checked)
                                      : prev,
                                  )
                                }
                                disabled={
                                  saving ||
                                  form.mode === 'inherit' ||
                                  locked ||
                                  Boolean(selectedKey?.revoked_at)
                                }
                              />
                            </li>
                          );
                        })}
                      </ul>
                    </section>
                  );
                })}
              </div>
            )}
          </div>

          <div
            className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/40"
            aria-live="polite"
          >
            <div className="flex items-center justify-between gap-2 mb-2">
              <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                Effective summary
              </h4>
              {previewLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-gray-400" aria-label="Updating preview" />
              ) : null}
            </div>
            {previewRows ? (
              <div className="space-y-1 text-sm text-gray-600 dark:text-gray-400">
                <p>
                  <span className="font-medium text-gray-800 dark:text-gray-200">
                    {enabledPreview.length}
                  </span>{' '}
                  tools enabled for calls
                  {deniedCount > 0 ? (
                    <>
                      {' '}
                      ·{' '}
                      <span className="font-medium text-gray-800 dark:text-gray-200">
                        {deniedCount}
                      </span>{' '}
                      denied
                    </>
                  ) : null}
                </p>
                {enabledPreview.length > 0 ? (
                  <p className="text-xs break-words">
                    {enabledPreview.join(', ')}
                  </p>
                ) : (
                  <p className="text-xs">No tools currently effective for this key.</p>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Preview unavailable.
              </p>
            )}
          </div>

          {dirty && (
            <div
              role="status"
              className="sticky bottom-0 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-700 dark:bg-amber-900/30"
            >
              <span className="flex items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-200">
                <BadgeCheck className="h-4 w-4" aria-hidden />
                Unsaved key capability changes
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleDiscard}
                  disabled={saving}
                >
                  Discard
                </Button>
                <Button onClick={handleSave} disabled={saving} size="sm">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {saving ? 'Saving…' : 'Save capabilities'}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

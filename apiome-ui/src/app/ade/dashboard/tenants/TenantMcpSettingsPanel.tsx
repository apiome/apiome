'use client';

/**
 * Tenant MCP Settings expandable panel — MTG-4.1 (#4780) + MTG-4.2 (#4781)
 * + MTG-4.3 (#4782) per-key capability editor + MTG-4.4 (#4783) non-admin
 * read-only + MTG-4.5 (#4784) disable confirm + MTG-5.1 (#4785) capability
 * presets.
 *
 * Loads MTG-3.1 policy + MTG-1.1 catalog + MTG-5.1 presets for the session's
 * current tenant. Toolsets use master switches; named packs apply a draft
 * matrix; optional advanced view exposes per-tool flags. Non-admins browse
 * the same controls disabled (GuideEditorClient pattern). When this row is
 * not the current tenant, shows a switch-tenant note (proxy is always
 * current-tenant scoped).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BadgeCheck,
  ChevronDown,
  ChevronUp,
  Loader2,
  Lock,
  Settings2,
} from 'lucide-react';
import { toast } from 'sonner';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Checkbox } from '@/app/components/ui/Checkbox';
import { Label } from '@/app/components/ui/Label';
import { Switch } from '@/app/components/ui/Switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { useDialog } from '@/app/components/providers/DialogProvider';
import {
  fetchMcpCapabilityPresets,
  fetchMcpPolicy,
  fetchMcpToolCatalog,
  putMcpPolicy,
  type McpCapabilityPresetItem,
  type TenantDefaultMode,
} from './mcpPolicyApi';
import { fetchMcpKeys } from './mcpKeysApi';
import {
  applyCapabilityPreset,
  buildMcpPolicyPutBody,
  groupToolsByToolset,
  hasMcpPolicyChanges,
  matchCapabilityPreset,
  mcpPolicyFormFromSources,
  MCP_CUSTOM_PRESET_ID,
  patchToolFlag,
  patchToolsetCeiling,
  validateMcpPolicyForm,
  type McpPolicyFormState,
} from './mcpPolicyForm';
import {
  findActiveKeysEffectivelyEnablingTools,
  formatToolsetDisableImpactMessage,
} from './mcpToolsetDisableImpact';
import TenantMcpKeyCapabilitiesEditor from './TenantMcpKeyCapabilitiesEditor';

export interface TenantMcpSettingsPanelProps {
  /** True when this row is the session's current tenant (loads live policy). */
  isCurrentTenant: boolean;
  /** True when the viewer is a tenant admin for this tenant. */
  isAdmin: boolean;
  /** Tenant display name for the non-current-tenant helper. */
  tenantName?: string;
}

const LIST_VS_CALL_HELP =
  'tools/list always returns the full catalog; ceiling, defaults, and anonymous flags only gate tools/call.';

const ADMIN_ONLY_COPY = 'Only tenant administrators can change MCP options.';

const MODE_LABELS: Record<TenantDefaultMode, string> = {
  all: 'All registry tools',
  inherit_registry: 'Inherit registry defaults',
  explicit: 'Explicit per-tool flags',
};

function titleCaseToolset(toolset: string): string {
  if (!toolset) return 'Other';
  return toolset.charAt(0).toUpperCase() + toolset.slice(1);
}

export default function TenantMcpSettingsPanel({
  isCurrentTenant,
  isAdmin,
  tenantName,
}: TenantMcpSettingsPanelProps) {
  const { confirm: confirmDialog } = useDialog();
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<McpPolicyFormState | null>(null);
  const [baseline, setBaseline] = useState<McpPolicyFormState | null>(null);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  /** Bumped after successful policy save so inherit key previews refresh. */
  const [policyRevision, setPolicyRevision] = useState(0);
  const [presets, setPresets] = useState<McpCapabilityPresetItem[]>([]);

  const readOnly = !isAdmin;
  const controlsDisabled = readOnly || saving;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [policy, catalog, presetBody] = await Promise.all([
        fetchMcpPolicy(),
        fetchMcpToolCatalog(),
        fetchMcpCapabilityPresets(),
      ]);
      const next = mcpPolicyFormFromSources(policy, catalog.tools ?? []);
      setForm(next);
      setBaseline(next);
      setPresets(presetBody.presets ?? []);
      setLoadedOnce(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load MCP settings';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isCurrentTenant || !expanded || loadedOnce) return;
    void load();
  }, [isCurrentTenant, expanded, loadedOnce, load]);

  const dirty = form && baseline && !readOnly ? hasMcpPolicyChanges(form, baseline) : false;
  const toolsetGroups = useMemo(
    () => (form ? groupToolsByToolset(form.tools) : []),
    [form],
  );
  const catalogItems = useMemo(
    () =>
      (form?.tools ?? []).map(({ tool_id, description, toolset }) => ({
        id: tool_id,
        description,
        toolset,
      })),
    [form],
  );
  const ceilingToolIds = useMemo(
    () => (baseline?.tools ?? []).filter((t) => t.in_ceiling).map((t) => t.tool_id),
    [baseline],
  );
  const activePresetId = useMemo(
    () => (form ? matchCapabilityPreset(form, presets) : MCP_CUSTOM_PRESET_ID),
    [form, presets],
  );

  const handleDiscard = () => {
    if (baseline) setForm(baseline);
    setError(null);
  };

  /** Apply a named pack to the draft, or no-op when Custom is chosen. */
  const handlePresetChange = (presetId: string) => {
    if (readOnly || presetId === MCP_CUSTOM_PRESET_ID) return;
    const pack = presets.find((p) => p.id === presetId);
    if (!pack) return;
    setForm((prev) => (prev ? applyCapabilityPreset(prev, pack.toolsets) : prev));
  };

  /**
   * Master toolset switch. Disabling prompts when ≥1 active key currently
   * effective-enables tools in the set (MTG-4.5); cancel leaves form unchanged.
   */
  const handleToolsetToggle = useCallback(
    async (toolset: string, enabled: boolean, toolIds: string[]) => {
      if (readOnly) return;
      if (!enabled && baseline) {
        try {
          const list = await fetchMcpKeys();
          const impacted = findActiveKeysEffectivelyEnablingTools(
            baseline,
            toolIds,
            list.keys ?? [],
          );
          if (impacted.length > 0) {
            const confirmed = await confirmDialog({
              title: `Disable ${titleCaseToolset(toolset)} toolset?`,
              message: formatToolsetDisableImpactMessage(toolset, impacted),
              variant: 'warning',
              confirmLabel: 'Disable toolset',
              cancelLabel: 'Cancel',
            });
            if (!confirmed) return;
          }
        } catch {
          // Key list failed — still warn so an impactful disable is never silent.
          const confirmed = await confirmDialog({
            title: `Disable ${titleCaseToolset(toolset)} toolset?`,
            message:
              `Disabling the ${toolset} toolset may remove tools from active MCP keys. ` +
              `Agents using those keys could lose access on the next call. Continue?`,
            variant: 'warning',
            confirmLabel: 'Disable toolset',
            cancelLabel: 'Cancel',
          });
          if (!confirmed) return;
        }
      }
      setForm((prev) => (prev ? patchToolsetCeiling(prev, toolset, enabled) : prev));
    },
    [baseline, confirmDialog, readOnly],
  );

  const handleSave = async () => {
    if (!form || readOnly) return;
    const validation = validateMcpPolicyForm(form);
    if (validation) {
      setError(validation);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await putMcpPolicy(buildMcpPolicyPutBody(form));
      const catalogTools = form.tools.map(({ tool_id, description, toolset }) => ({
        id: tool_id,
        description,
        toolset,
      }));
      const next = mcpPolicyFormFromSources(saved, catalogTools);
      setForm(next);
      setBaseline(next);
      setPolicyRevision((n) => n + 1);
      toast.success('MCP settings saved');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save MCP settings';
      setError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-base font-semibold flex items-center gap-2 cursor-pointer text-gray-700 dark:text-gray-300 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
          aria-expanded={expanded}
        >
          <div className="p-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-900/30">
            <Settings2 className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
          </div>
          MCP Settings
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>

      {expanded && (
        <div className="space-y-4">
          {!isCurrentTenant ? (
            <div className="flex items-start gap-3 rounded-lg border border-slate-300 bg-slate-100 p-4 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              <Lock className="mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden />
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Select{tenantName ? ` ${tenantName}` : ' this tenant'} as your current tenant to
                view or edit MCP settings.
              </p>
            </div>
          ) : (
            <>
              {readOnly && (
                <div className="flex items-start gap-3 rounded-lg border border-slate-300 bg-slate-100 p-4 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
                  <Lock className="mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden />
                  <p className="text-sm">{ADMIN_ONLY_COPY}</p>
                </div>
              )}

              <p className="text-sm text-gray-500 dark:text-gray-400">{LIST_VS_CALL_HELP}</p>

              {error && <Alert variant="error">{error}</Alert>}

              {loading && !form ? (
                <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 py-4">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading MCP settings…
                </div>
              ) : form ? (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor="mcp-default-mode">Default mode</Label>
                      <Select
                        value={form.default_mode}
                        onValueChange={(value) =>
                          setForm((prev) =>
                            prev
                              ? { ...prev, default_mode: value as TenantDefaultMode }
                              : prev,
                          )
                        }
                        disabled={controlsDisabled}
                      >
                        <SelectTrigger id="mcp-default-mode">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(MODE_LABELS) as TenantDefaultMode[]).map((mode) => (
                            <SelectItem key={mode} value={mode}>
                              {MODE_LABELS[mode]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-end gap-3 pb-1">
                      <Switch
                        id="mcp-allow-anonymous"
                        aria-label="Allow anonymous MCP calls"
                        checked={form.allow_anonymous_mcp}
                        onCheckedChange={(checked) =>
                          setForm((prev) =>
                            prev ? { ...prev, allow_anonymous_mcp: checked } : prev,
                          )
                        }
                        disabled={controlsDisabled}
                      />
                      <Label
                        htmlFor="mcp-allow-anonymous"
                        className={readOnly ? undefined : 'cursor-pointer'}
                      >
                        Allow anonymous MCP calls
                      </Label>
                    </div>
                  </div>

                  {presets.length > 0 && (
                    <div className="space-y-2 max-w-md">
                      <Label htmlFor="mcp-capability-preset">Capability profile</Label>
                      <Select
                        value={activePresetId}
                        onValueChange={handlePresetChange}
                        disabled={controlsDisabled}
                      >
                        <SelectTrigger
                          id="mcp-capability-preset"
                          aria-label="Capability profile"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {presets.map((preset) => (
                            <SelectItem key={preset.id} value={preset.id}>
                              {preset.label}
                            </SelectItem>
                          ))}
                          <SelectItem value={MCP_CUSTOM_PRESET_ID}>Custom</SelectItem>
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        Named packs set toolset ceilings in one click; Custom stays
                        editable after apply.
                      </p>
                    </div>
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      Toolsets
                    </h3>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id="mcp-advanced-tools"
                        checked={advanced}
                        onCheckedChange={(checked) => setAdvanced(checked === true)}
                        disabled={saving}
                      />
                      <Label htmlFor="mcp-advanced-tools" className="cursor-pointer text-sm">
                        Advanced: individual tools
                      </Label>
                    </div>
                  </div>

                  {toolsetGroups.length === 0 ? (
                    <p className="text-sm text-gray-500 dark:text-gray-400 py-2">
                      No MCP tools in the registry catalog.
                    </p>
                  ) : (
                    <div className="space-y-4">
                      {toolsetGroups.map((group) => (
                        <section
                          key={group.toolset}
                          aria-label={`${group.toolset} toolset`}
                          className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
                        >
                          <div className="flex items-center gap-4 border-b border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/50">
                            <Switch
                              aria-label={`Enable ${group.toolset} toolset`}
                              checked={group.ceilingState === 'all'}
                              indeterminate={group.ceilingState === 'mixed'}
                              onCheckedChange={(checked) =>
                                void handleToolsetToggle(
                                  group.toolset,
                                  checked,
                                  group.tools.map((t) => t.tool_id),
                                )
                              }
                              disabled={controlsDisabled}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="text-sm font-semibold text-gray-900 dark:text-white">
                                {titleCaseToolset(group.toolset)}
                              </div>
                              <div className="text-xs text-gray-500 dark:text-gray-400">
                                {group.inCeilingCount} of {group.tools.length} tools in ceiling
                              </div>
                            </div>
                          </div>

                          {advanced && (
                            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                              {group.tools.map((tool) => (
                                <li
                                  key={tool.tool_id}
                                  className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center"
                                >
                                  <div className="min-w-0 flex-1">
                                    <div className="text-sm font-medium text-gray-900 dark:text-white">
                                      {tool.tool_id}
                                    </div>
                                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                      {tool.description}
                                    </div>
                                  </div>
                                  <div className="flex flex-wrap items-center gap-4">
                                    <div className="flex items-center gap-2">
                                      <Switch
                                        aria-label={`${tool.tool_id} in ceiling`}
                                        checked={tool.in_ceiling}
                                        onCheckedChange={(checked) =>
                                          setForm((prev) =>
                                            prev
                                              ? patchToolFlag(
                                                  prev,
                                                  tool.tool_id,
                                                  'in_ceiling',
                                                  checked,
                                                )
                                              : prev,
                                          )
                                        }
                                        disabled={controlsDisabled}
                                      />
                                      <span className="text-xs text-gray-600 dark:text-gray-400">
                                        Ceiling
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      <Switch
                                        aria-label={`${tool.tool_id} default enabled`}
                                        checked={tool.default_enabled}
                                        onCheckedChange={(checked) =>
                                          setForm((prev) =>
                                            prev
                                              ? patchToolFlag(
                                                  prev,
                                                  tool.tool_id,
                                                  'default_enabled',
                                                  checked,
                                                )
                                              : prev,
                                          )
                                        }
                                        disabled={controlsDisabled || !tool.in_ceiling}
                                      />
                                      <span className="text-xs text-gray-600 dark:text-gray-400">
                                        Default
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                      <Switch
                                        aria-label={`${tool.tool_id} anonymous enabled`}
                                        checked={tool.anonymous_enabled}
                                        onCheckedChange={(checked) =>
                                          setForm((prev) =>
                                            prev
                                              ? patchToolFlag(
                                                  prev,
                                                  tool.tool_id,
                                                  'anonymous_enabled',
                                                  checked,
                                                )
                                              : prev,
                                          )
                                        }
                                        disabled={controlsDisabled}
                                      />
                                      <span className="text-xs text-gray-600 dark:text-gray-400">
                                        Anonymous
                                      </span>
                                    </div>
                                  </div>
                                </li>
                              ))}
                            </ul>
                          )}
                        </section>
                      ))}
                    </div>
                  )}

                  {dirty && (
                    <div
                      role="status"
                      className="sticky bottom-0 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-700 dark:bg-amber-900/30"
                    >
                      <span className="flex items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-200">
                        <BadgeCheck className="h-4 w-4" aria-hidden />
                        Unsaved MCP settings changes
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
                          {saving ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : null}
                          {saving ? 'Saving…' : 'Save changes'}
                        </Button>
                      </div>
                    </div>
                  )}

                  {isAdmin ? (
                    <TenantMcpKeyCapabilitiesEditor
                      catalog={catalogItems}
                      ceilingToolIds={ceilingToolIds}
                      policyRevision={policyRevision}
                      isAdmin={isAdmin}
                    />
                  ) : null}
                </>
              ) : null}
            </>
          )}
        </div>
      )}
    </div>
  );
}

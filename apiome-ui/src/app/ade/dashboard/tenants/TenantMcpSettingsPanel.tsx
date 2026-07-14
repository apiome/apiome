'use client';

/**
 * Tenant MCP Settings expandable panel — MTG-4.1 (#4780) + MTG-4.2 (#4781)
 * + MTG-4.3 (#4782) per-key capability editor.
 *
 * Loads MTG-3.1 policy + MTG-1.1 catalog for the session's current tenant.
 * Toolsets use master switches; optional advanced view exposes per-tool flags.
 * When `editable` is false (non-current tenant admin panel), shows a Style
 * Guides–style read-only note instead of the form.
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
import {
  fetchMcpPolicy,
  fetchMcpToolCatalog,
  putMcpPolicy,
  type TenantDefaultMode,
} from './mcpPolicyApi';
import {
  buildMcpPolicyPutBody,
  groupToolsByToolset,
  hasMcpPolicyChanges,
  mcpPolicyFormFromSources,
  patchToolFlag,
  patchToolsetCeiling,
  validateMcpPolicyForm,
  type McpPolicyFormState,
} from './mcpPolicyForm';
import TenantMcpKeyCapabilitiesEditor from './TenantMcpKeyCapabilitiesEditor';

export interface TenantMcpSettingsPanelProps {
  /** When false, show a disabled note instead of the editable form. */
  editable: boolean;
  /** Tenant display name for the disabled helper (optional). */
  tenantName?: string;
}

const LIST_VS_CALL_HELP =
  'tools/list always returns the full catalog; ceiling, defaults, and anonymous flags only gate tools/call.';

const ADMIN_ONLY_COPY =
  'Only tenant administrators can change MCP tool policy. You can browse the catalog.';

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
  editable,
  tenantName,
}: TenantMcpSettingsPanelProps) {
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

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [policy, catalog] = await Promise.all([fetchMcpPolicy(), fetchMcpToolCatalog()]);
      const next = mcpPolicyFormFromSources(policy, catalog.tools ?? []);
      setForm(next);
      setBaseline(next);
      setLoadedOnce(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load MCP settings';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!editable || !expanded || loadedOnce) return;
    void load();
  }, [editable, expanded, loadedOnce, load]);

  const dirty = form && baseline ? hasMcpPolicyChanges(form, baseline) : false;
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

  const handleDiscard = () => {
    if (baseline) setForm(baseline);
    setError(null);
  };

  const handleSave = async () => {
    if (!form) return;
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
          {!editable ? (
            <div className="flex items-start gap-3 rounded-lg border border-slate-300 bg-slate-100 p-4 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              <Lock className="mt-0.5 h-5 w-5 flex-shrink-0" aria-hidden />
              <div className="space-y-1 text-sm">
                <p>{ADMIN_ONLY_COPY}</p>
                <p className="text-slate-500 dark:text-slate-400">
                  Select{tenantName ? ` ${tenantName}` : ' this tenant'} as your current tenant to
                  edit MCP settings.
                </p>
              </div>
            </div>
          ) : (
            <>
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
                        disabled={saving}
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
                        disabled={saving}
                      />
                      <Label htmlFor="mcp-allow-anonymous" className="cursor-pointer">
                        Allow anonymous MCP calls
                      </Label>
                    </div>
                  </div>

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
                                setForm((prev) =>
                                  prev
                                    ? patchToolsetCeiling(prev, group.toolset, checked)
                                    : prev,
                                )
                              }
                              disabled={saving}
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
                                        disabled={saving}
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
                                        disabled={saving || !tool.in_ceiling}
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
                                        disabled={saving}
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

                  <TenantMcpKeyCapabilitiesEditor
                    catalog={catalogItems}
                    ceilingToolIds={ceilingToolIds}
                    policyRevision={policyRevision}
                  />
                </>
              ) : null}
            </>
          )}
        </div>
      )}
    </div>
  );
}

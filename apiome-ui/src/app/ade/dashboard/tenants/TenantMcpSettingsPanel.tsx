'use client';

/**
 * Tenant MCP Settings expandable panel — MTG-4.1 (#4780).
 *
 * Loads MTG-3.1 policy + MTG-1.1 catalog for the session's current tenant.
 * When `editable` is false (non-current tenant admin panel), shows a short
 * disabled note instead of the form.
 */

import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, Loader2, Save, Settings2 } from 'lucide-react';
import { toast } from 'sonner';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Checkbox } from '@/app/components/ui/Checkbox';
import { Label } from '@/app/components/ui/Label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import {
  dashboardTableTheadClass,
  dashboardTableWrapClass,
  dashboardTbodyClass,
  dashboardThClass,
  dashboardTrHoverClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  fetchMcpPolicy,
  fetchMcpToolCatalog,
  putMcpPolicy,
  type TenantDefaultMode,
} from './mcpPolicyApi';
import {
  buildMcpPolicyPutBody,
  hasMcpPolicyChanges,
  mcpPolicyFormFromSources,
  patchToolFlag,
  validateMcpPolicyForm,
  type McpPolicyFormState,
} from './mcpPolicyForm';

export interface TenantMcpSettingsPanelProps {
  /** When false, show a disabled note instead of the editable form. */
  editable: boolean;
  /** Tenant display name for the disabled helper (optional). */
  tenantName?: string;
}

const LIST_VS_CALL_HELP =
  'tools/list always returns the full catalog; ceiling, defaults, and anonymous flags only gate tools/call.';

const MODE_LABELS: Record<TenantDefaultMode, string> = {
  all: 'All registry tools',
  inherit_registry: 'Inherit registry defaults',
  explicit: 'Explicit per-tool flags',
};

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
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Select{tenantName ? ` ${tenantName}` : ' this tenant'} to edit MCP settings.
            </p>
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
                      <Checkbox
                        id="mcp-allow-anonymous"
                        checked={form.allow_anonymous_mcp}
                        onCheckedChange={(checked) =>
                          setForm((prev) =>
                            prev
                              ? { ...prev, allow_anonymous_mcp: checked === true }
                              : prev,
                          )
                        }
                        disabled={saving}
                      />
                      <Label htmlFor="mcp-allow-anonymous" className="cursor-pointer">
                        Allow anonymous MCP calls
                      </Label>
                    </div>
                  </div>

                  <div className={dashboardTableWrapClass}>
                    <table className="min-w-full">
                      <thead className={dashboardTableTheadClass}>
                        <tr>
                          <th scope="col" className={dashboardThClass}>
                            Tool
                          </th>
                          <th scope="col" className={dashboardThClass}>
                            In ceiling
                          </th>
                          <th scope="col" className={dashboardThClass}>
                            Default enabled
                          </th>
                          <th scope="col" className={dashboardThClass}>
                            Anonymous
                          </th>
                        </tr>
                      </thead>
                      <tbody className={dashboardTbodyClass}>
                        {form.tools.length === 0 ? (
                          <tr>
                            <td
                              colSpan={4}
                              className="px-6 py-8 text-center text-sm text-gray-500 dark:text-gray-400"
                            >
                              No MCP tools in the registry catalog.
                            </td>
                          </tr>
                        ) : (
                          form.tools.map((tool) => (
                            <tr key={tool.tool_id} className={dashboardTrHoverClass}>
                              <td className="px-6 py-3 align-top">
                                <div className="text-sm font-semibold text-gray-900 dark:text-white">
                                  {tool.tool_id}
                                </div>
                                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                  {tool.toolset} — {tool.description}
                                </div>
                              </td>
                              <td className="px-6 py-3">
                                <Checkbox
                                  aria-label={`${tool.tool_id} in ceiling`}
                                  checked={tool.in_ceiling}
                                  onCheckedChange={(checked) =>
                                    setForm((prev) =>
                                      prev
                                        ? patchToolFlag(
                                            prev,
                                            tool.tool_id,
                                            'in_ceiling',
                                            checked === true,
                                          )
                                        : prev,
                                    )
                                  }
                                  disabled={saving}
                                />
                              </td>
                              <td className="px-6 py-3">
                                <Checkbox
                                  aria-label={`${tool.tool_id} default enabled`}
                                  checked={tool.default_enabled}
                                  onCheckedChange={(checked) =>
                                    setForm((prev) =>
                                      prev
                                        ? patchToolFlag(
                                            prev,
                                            tool.tool_id,
                                            'default_enabled',
                                            checked === true,
                                          )
                                        : prev,
                                    )
                                  }
                                  disabled={saving || !tool.in_ceiling}
                                />
                              </td>
                              <td className="px-6 py-3">
                                <Checkbox
                                  aria-label={`${tool.tool_id} anonymous enabled`}
                                  checked={tool.anonymous_enabled}
                                  onCheckedChange={(checked) =>
                                    setForm((prev) =>
                                      prev
                                        ? patchToolFlag(
                                            prev,
                                            tool.tool_id,
                                            'anonymous_enabled',
                                            checked === true,
                                          )
                                        : prev,
                                    )
                                  }
                                  disabled={saving}
                                />
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>

                  {dirty && (
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <Button onClick={handleSave} disabled={saving} size="sm">
                        {saving ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4" />
                        )}
                        {saving ? 'Saving…' : 'Save'}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleDiscard}
                        disabled={saving}
                      >
                        Discard
                      </Button>
                    </div>
                  )}
                </>
              ) : null}
            </>
          )}
        </div>
      )}
    </div>
  );
}

"use client";

/**
 * Endpoint-detail "Settings" tab (V2-MCP-24.9 / MCAT-10.9).
 *
 * Rendered inside the 10.2 detail shell. Lets the owner edit an endpoint's identity & connection
 * (name, URL, transport, visibility, discovery cadence) and manage its lifecycle (enable/disable,
 * delete). Identity edits persist via `PATCH /api/mcp/endpoints/{id}`; delete (with a typed confirm
 * that names the cascade) calls `DELETE` and surfaces the returned teardown summary. Inline
 * validation reuses the import-source URL/transport rules; every style is a design-token class.
 *
 * The component is self-contained: it owns the form state and the network calls, and lifts results
 * to the parent through `onSaved` (an updated endpoint) and `onDeleted` (the teardown summary).
 */

import { useEffect, useMemo, useState } from "react";
import { Loader2, Power, PowerOff, Save, Server, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { useDialog } from "@/app/components/providers/DialogProvider";
import { Button } from "@/app/components/ui/Button";
import { Input } from "@/app/components/ui/Input";
import { Label } from "@/app/components/ui/Label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/app/components/ui/Select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/app/components/ui/AlertDialog";
import { dashboardPanelPaddedClass } from "@/app/components/ade/dashboard/dashboardScreenClasses";
import {
  MCP_TRANSPORT_OPTIONS,
  type McpTransport,
} from "@/app/components/ade/dashboard/mcp/mcpImportFlow";
import {
  mcpEndpointDetailFromPayload,
  type McpEndpointDetail,
} from "@/app/components/ade/dashboard/mcp/mcpBrowseUi";
import {
  MCP_DELETE_CONFIRM_WORD,
  MCP_CADENCE_DEFAULT_SELECT_VALUE,
  MCP_SUB_DAILY_CADENCE_CONFIRM_MESSAGE,
  MCP_VISIBILITY_OPTIONS,
  buildSettingsPatchBody,
  cadenceSelectValueFromForm,
  hasSettingsChanges,
  isDeleteConfirmed,
  mcpCadenceOptions,
  mcpSettingsFormFromEndpoint,
  mcpTeardownSummaryFromPayload,
  normalizeCadenceSelectValue,
  settingsPatchNeedsSubDailyCadenceConfirm,
  validateMcpSettingsForm,
  type McpSettingsForm,
  type McpTeardownSummary,
  type McpVisibility,
} from "@/app/components/ade/dashboard/mcp/mcpSettingsForm";

export interface McpEndpointSettingsProps {
  endpoint: McpEndpointDetail;
  /** Called with the updated record after an identity edit or an enable/disable toggle persists. */
  onSaved: (updated: McpEndpointDetail) => void;
  /** Called after the endpoint is deleted, with the cascade teardown summary. */
  onDeleted: (summary: McpTeardownSummary) => void;
}

const fieldLabelClass = "mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-300";
const helpTextClass = "mt-1 text-xs text-gray-500 dark:text-gray-400";

/** Read an error message out of a `{ error }` JSON body, falling back to a status line. */
function errorFromResponse(data: unknown, statusText: string): string {
  if (data && typeof data === "object" && "error" in data) {
    const err = (data as { error: unknown }).error;
    if (typeof err === "string" && err.trim()) return err;
  }
  return statusText || "Request failed.";
}

export default function McpEndpointSettings({
  endpoint,
  onSaved,
  onDeleted,
}: McpEndpointSettingsProps) {
  const { confirm: confirmDialog } = useDialog();
  const [form, setForm] = useState<McpSettingsForm>(() => mcpSettingsFormFromEndpoint(endpoint));
  /** Which mutation is in flight ("save" | "enabled" | "delete"), or null when idle. */
  const [busy, setBusy] = useState<string | null>(null);
  /** Inline validation error for the identity form (shown above the Save button). */
  const [formError, setFormError] = useState<string | null>(null);
  /** Whether the destructive delete dialog is open. */
  const [deleteOpen, setDeleteOpen] = useState(false);
  /** The user's typed confirmation in the delete dialog. */
  const [deleteConfirm, setDeleteConfirm] = useState("");

  // Re-seed the form whenever the endpoint's editable fields change by value (e.g. after a save
  // re-fetches the record). Keyed on those fields only, so a header publish/enable toggle — which
  // does not touch them — never discards in-progress edits.
  const editableSignature = [
    endpoint.name,
    endpoint.endpoint_url,
    endpoint.transport,
    endpoint.visibility,
    endpoint.discovery_cadence_seconds ?? "",
  ].join(" ");
  useEffect(() => {
    setForm(mcpSettingsFormFromEndpoint(endpoint));
    setFormError(null);
    // editableSignature captures every endpoint field the form reads; endpoint is read inside.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editableSignature]);

  const set = <K extends keyof McpSettingsForm>(key: K, value: McpSettingsForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const cadenceOptions = useMemo(
    () => mcpCadenceOptions(endpoint.discovery_cadence_seconds),
    [endpoint.discovery_cadence_seconds],
  );

  const patchBody = useMemo(() => buildSettingsPatchBody(form, endpoint), [form, endpoint]);
  const dirty = hasSettingsChanges(patchBody);

  /** PATCH the endpoint with `body`, returning the parsed updated record or throwing on error. */
  async function patchEndpoint(body: Record<string, unknown>): Promise<McpEndpointDetail> {
    const res = await fetch(`/api/mcp/endpoints/${endpoint.id}`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(errorFromResponse(data, res.statusText));
    const updated = mcpEndpointDetailFromPayload(data);
    if (!updated) throw new Error("The server returned an unexpected response.");
    return updated;
  }

  /** Validate and persist the identity/connection form. */
  async function handleSave() {
    const validation = validateMcpSettingsForm(form);
    if (validation) {
      setFormError(validation);
      return;
    }
    setFormError(null);
    if (!hasSettingsChanges(patchBody)) {
      toast.info("No changes to save.");
      return;
    }
    if (settingsPatchNeedsSubDailyCadenceConfirm(patchBody)) {
      const confirmed = await confirmDialog({
        title: "Are you sure?",
        message: MCP_SUB_DAILY_CADENCE_CONFIRM_MESSAGE,
        variant: "warning",
        confirmLabel: "Save changes",
        cancelLabel: "Cancel",
      });
      if (!confirmed) return;
    }
    setBusy("save");
    try {
      const updated = await patchEndpoint(patchBody as Record<string, unknown>);
      onSaved(updated);
      toast.success("Endpoint settings saved.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save settings.");
    } finally {
      setBusy(null);
    }
  }

  /** Toggle the endpoint's enabled state (removing/restoring it from the discovery sweep). */
  async function handleToggleEnabled() {
    const next = !endpoint.enabled;
    setBusy("enabled");
    try {
      const updated = await patchEndpoint({ enabled: next });
      onSaved(updated);
      toast.success(next ? "Endpoint enabled." : "Endpoint disabled.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update the endpoint.");
    } finally {
      setBusy(null);
    }
  }

  /** Delete the endpoint (typed-confirm gated) and surface the teardown summary. */
  async function handleDelete() {
    if (!isDeleteConfirmed(deleteConfirm)) return;
    setBusy("delete");
    try {
      const res = await fetch(`/api/mcp/endpoints/${endpoint.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorFromResponse(data, res.statusText));
      setDeleteOpen(false);
      onDeleted(mcpTeardownSummaryFromPayload(data));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not delete the endpoint.");
    } finally {
      setBusy(null);
    }
  }

  const saving = busy === "save";
  const togglingEnabled = busy === "enabled";
  const deleting = busy === "delete";
  const anyBusy = busy !== null;

  return (
    <div className="space-y-8">
      {/* Identity & connection ------------------------------------------------------------- */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:gap-8">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
            <Server className="h-4 w-4 text-indigo-500" aria-hidden />
            Identity &amp; connection
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            How this endpoint appears in your catalog and how discovery connects to it. Changing the
            URL or transport takes effect on the next discovery run.
          </p>
        </div>
        <div className={`${dashboardPanelPaddedClass} space-y-4 lg:col-span-2`}>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="md:col-span-2">
              <Label htmlFor="mcp-settings-name" className={fieldLabelClass}>
                Name <span className="text-red-500">*</span>
              </Label>
              <Input
                id="mcp-settings-name"
                type="text"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
              />
            </div>

            <div className="md:col-span-2">
              <Label htmlFor="mcp-settings-url" className={fieldLabelClass}>
                Endpoint URL <span className="text-red-500">*</span>
              </Label>
              <Input
                id="mcp-settings-url"
                type="text"
                inputMode="url"
                placeholder="https://mcp.example.com/sse"
                value={form.endpointUrl}
                onChange={(e) => set("endpointUrl", e.target.value)}
              />
              <p className={helpTextClass}>The MCP server&apos;s connection URL.</p>
            </div>

            <div>
              <Label htmlFor="mcp-settings-transport" className={fieldLabelClass}>
                Transport
              </Label>
              <Select
                value={form.transport}
                onValueChange={(v) => set("transport", v as McpTransport)}
              >
                <SelectTrigger id="mcp-settings-transport">
                  <SelectValue placeholder="Select transport" />
                </SelectTrigger>
                <SelectContent>
                  {MCP_TRANSPORT_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="mcp-settings-visibility" className={fieldLabelClass}>
                Visibility
              </Label>
              <Select
                value={form.visibility}
                onValueChange={(v) => set("visibility", v as McpVisibility)}
              >
                <SelectTrigger id="mcp-settings-visibility">
                  <SelectValue placeholder="Select visibility" />
                </SelectTrigger>
                <SelectContent>
                  {MCP_VISIBILITY_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label htmlFor="mcp-settings-cadence" className={fieldLabelClass}>
                Discovery cadence
              </Label>
              <Select
                value={cadenceSelectValueFromForm(form.cadence)}
                onValueChange={(v) => set("cadence", normalizeCadenceSelectValue(v))}
              >
                <SelectTrigger id="mcp-settings-cadence">
                  <SelectValue placeholder="Default cadence" />
                </SelectTrigger>
                <SelectContent>
                  {cadenceOptions.map((opt) => (
                    <SelectItem
                      key={opt.value || MCP_CADENCE_DEFAULT_SELECT_VALUE}
                      value={opt.value || MCP_CADENCE_DEFAULT_SELECT_VALUE}
                    >
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className={helpTextClass}>How often this endpoint is re-discovered automatically.</p>
            </div>
          </div>

          {formError ? (
            <p
              role="alert"
              className="flex items-center gap-1.5 text-sm text-red-600 dark:text-red-400"
            >
              <TriangleAlert className="h-4 w-4" aria-hidden />
              {formError}
            </p>
          ) : null}

          <div className="flex items-center justify-end gap-3 border-t border-gray-100 pt-4 dark:border-gray-700">
            {dirty && !saving ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-amber-600 dark:text-amber-400">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
                Unsaved changes
              </span>
            ) : null}
            <Button
              type="button"
              onClick={() => void handleSave()}
              disabled={anyBusy || !dirty}
              title={dirty ? "Save changes" : "No changes to save"}
            >
              {saving ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Save className="h-4 w-4" aria-hidden />
              )}
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </div>
      </section>

      {/* Lifecycle ------------------------------------------------------------------------- */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:gap-8">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
            <Power className="h-4 w-4 text-indigo-500" aria-hidden />
            Lifecycle
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            A disabled endpoint stays in the catalog with its versions intact but is skipped by
            scheduled discovery.
          </p>
        </div>
        <div className={`${dashboardPanelPaddedClass} lg:col-span-2`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                  endpoint.enabled ? "bg-emerald-500" : "bg-gray-400 dark:bg-gray-600"
                }`}
                aria-hidden
              />
              <div>
                <div className="text-sm font-medium text-gray-900 dark:text-white">
                  {endpoint.enabled ? "Endpoint is enabled" : "Endpoint is disabled"}
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {endpoint.enabled
                    ? "It is included in the scheduled discovery sweep."
                    : "It is skipped by the scheduled discovery sweep."}
                </p>
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleToggleEnabled()}
              disabled={anyBusy}
            >
              {togglingEnabled ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : endpoint.enabled ? (
                <PowerOff className="h-4 w-4" aria-hidden />
              ) : (
                <Power className="h-4 w-4" aria-hidden />
              )}
              {endpoint.enabled ? "Disable" : "Enable"}
            </Button>
          </div>
        </div>
      </section>

      {/* Danger zone ----------------------------------------------------------------------- */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:gap-8">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-red-700 dark:text-red-400">
            <TriangleAlert className="h-4 w-4" aria-hidden />
            Danger zone
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
            Destructive actions that cannot be undone.
          </p>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50/60 p-4 dark:border-red-900 dark:bg-red-950/20 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-gray-900 dark:text-white">
                Delete this endpoint
              </div>
              <p className="text-xs text-gray-600 dark:text-gray-400">
                Permanently removes the endpoint and purges its versions, discovery jobs, and stored
                credentials. This cannot be undone.
              </p>
            </div>
            <Button
              type="button"
              variant="destructive"
              onClick={() => {
                setDeleteConfirm("");
                setDeleteOpen(true);
              }}
              disabled={anyBusy}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              Delete endpoint
            </Button>
          </div>
        </div>
      </section>

      <AlertDialog open={deleteOpen} onOpenChange={(open) => !deleting && setDeleteOpen(open)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{endpoint.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently deletes the endpoint and cascades to its{" "}
              <strong>versions</strong>, <strong>discovery jobs</strong>, and stored{" "}
              <strong>credentials</strong>. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div>
            <Label htmlFor="mcp-delete-confirm" className={fieldLabelClass}>
              Type <span className="font-mono font-semibold">{MCP_DELETE_CONFIRM_WORD}</span> to
              confirm
            </Label>
            <Input
              id="mcp-delete-confirm"
              type="text"
              autoComplete="off"
              value={deleteConfirm}
              onChange={(e) => setDeleteConfirm(e.target.value)}
              placeholder={MCP_DELETE_CONFIRM_WORD}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 text-white hover:bg-red-700"
              disabled={!isDeleteConfirmed(deleteConfirm) || deleting}
              onClick={(e) => {
                // Keep the dialog mounted while the request runs; close it ourselves on success.
                e.preventDefault();
                void handleDelete();
              }}
            >
              {deleting ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="h-4 w-4" aria-hidden />
              )}
              {deleting ? "Deleting…" : "Delete endpoint"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

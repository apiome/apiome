'use client';

import React, { useState, useEffect } from 'react';
import { Server, Plus, Trash2, Pencil } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import { useStudio } from '../../StudioContext';
import { useDialog } from '../../../../components/providers/DialogProvider';
import {
  getServersForVersion,
  createServer,
  updateServer,
  deleteServer,
  type VersionServerRecord,
  type VersionServerInput,
  type ServerVariable,
} from '../../../../../../lib/db/helper-version-servers';
import { useDarkMode } from '../../../../hooks/useDarkMode';
import { Input } from '../../../../components/ui/Input';
import { Label } from '../../../../components/ui/Label';
import { Textarea } from '../../../../components/ui/Textarea';
import { Button } from '../../../../components/ui/Button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../../components/ui/Select';

const ENVIRONMENT_OPTIONS: { value: string; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'dev', label: 'Development' },
  { value: 'staging', label: 'Staging' },
  { value: 'prod', label: 'Production' },
];

type VariableFormEntry = { id: string; name: string; default: string; enum: string; description: string };

export default function ServersPanel({ onRefresh }: { onRefresh?: () => void }) {
  const { selectedVersionId } = useStudio();
  const { confirm: confirmDialog, alert: alertDialog } = useDialog();
  const isDark = useDarkMode();
  const [servers, setServers] = useState<VersionServerRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<VersionServerRecord | null>(null);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [description, setDescription] = useState('');
  const [environment, setEnvironment] = useState('none');
  const [variables, setVariables] = useState<VariableFormEntry[]>([]);
  const [formError, setFormError] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  function variablesToRecord(entries: VariableFormEntry[]): Record<string, ServerVariable> | null {
    const out: Record<string, ServerVariable> = {};
    for (const e of entries) {
      const n = e.name?.trim();
      if (!n) continue;
      const def = e.default?.trim() ?? '';
      const enumList = e.enum?.split(',').map((s) => s.trim()).filter(Boolean);
      out[n] = {
        default: def,
        ...(enumList.length > 0 ? { enum: enumList } : {}),
        ...(e.description?.trim() ? { description: e.description.trim() } : {}),
      };
    }
    return Object.keys(out).length ? out : null;
  }

  function recordToVariables(v: Record<string, ServerVariable> | null): VariableFormEntry[] {
    if (!v || !Object.keys(v).length) return [];
    return Object.entries(v).map(([varName, s], i) => ({
      id: `var-${varName}-${i}`,
      name: varName,
      default: s.default ?? '',
      enum: Array.isArray(s.enum) ? s.enum.join(', ') : '',
      description: s.description ?? '',
    }));
  }

  const addVariable = () => {
    setVariables((prev) => [...prev, { id: `var-new-${Date.now()}`, name: '', default: '', enum: '', description: '' }]);
  };

  const updateVariable = (id: string, field: keyof VariableFormEntry, value: string) => {
    setVariables((prev) => prev.map((v) => (v.id === id ? { ...v, [field]: value } : v)));
  };

  const removeVariable = (id: string) => {
    setVariables((prev) => prev.filter((v) => v.id !== id));
  };

  const loadServers = async () => {
    if (!selectedVersionId) {
      setServers([]);
      return;
    }
    setIsLoading(true);
    try {
      const list = await getServersForVersion(selectedVersionId);
      setServers(list);
    } catch (err) {
      console.error('Error loading servers:', err);
      setServers([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadServers();
  }, [selectedVersionId]);

  const resetForm = () => {
    setEditingServer(null);
    setName('');
    setUrl('');
    setDescription('');
    setEnvironment('none');
    setVariables([]);
    setFormError('');
  };

  const handleAdd = () => {
    resetForm();
    setDialogOpen(true);
  };

  const handleEdit = (server: VersionServerRecord) => {
    setEditingServer(server);
    setName(server.name ?? '');
    setUrl(server.url ?? '');
    setDescription(server.description ?? '');
    setEnvironment(server.environment && ['dev', 'staging', 'prod'].includes(server.environment) ? server.environment : 'none');
    setVariables(recordToVariables(server.variables ?? null));
    setFormError('');
    setDialogOpen(true);
  };

  const handleSave = async () => {
    const urlTrim = url?.trim();
    if (!urlTrim) {
      setFormError('URL is required');
      return;
    }
    if (!selectedVersionId) return;
    setIsSaving(true);
    setFormError('');
    try {
      const variablesRecord = variablesToRecord(variables);
      if (editingServer) {
        const result = await updateServer(editingServer.id, {
          name: name.trim() || undefined,
          url: urlTrim,
          description: description.trim() || undefined,
          variables: variablesRecord,
          environment: (environment && environment !== 'none' ? environment.trim() : null),
        });
        if (result.success && result.server) {
          setServers((prev) => prev.map((s) => (s.id === editingServer.id ? result.server! : s)));
          setDialogOpen(false);
          onRefresh?.();
        } else {
          setFormError(result.error ?? 'Failed to update server');
        }
      } else {
        const result = await createServer(selectedVersionId, {
          name: name.trim() || undefined,
          url: urlTrim,
          description: description.trim() || undefined,
          sort_order: servers.length,
          variables: variablesRecord,
          environment: (environment && environment !== 'none' ? environment.trim() : null),
        });
        if (result.success && result.server) {
          setServers((prev) => [...prev, result.server!]);
          setDialogOpen(false);
          onRefresh?.();
        } else {
          setFormError(result.error ?? 'Failed to create server');
        }
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async (server: VersionServerRecord) => {
    const confirmed = await confirmDialog({
      title: 'Delete Server',
      message: `Delete server "${server.name || server.url}"? This will remove it from the OpenAPI spec.`,
      variant: 'danger',
      confirmLabel: 'Delete',
      cancelLabel: 'Cancel',
    });
    if (!confirmed) return;
    try {
      const result = await deleteServer(server.id);
      if (result.success) {
        setServers((prev) => prev.filter((s) => s.id !== server.id));
        onRefresh?.();
      } else {
        await alertDialog({
          title: 'Error',
          message: result.error ?? 'Failed to delete server',
          variant: 'error',
        });
      }
    } catch (err) {
      await alertDialog({
        title: 'Error',
        message: err instanceof Error ? err.message : 'Unknown error',
        variant: 'error',
      });
    }
  };

  return (
    <div className="px-4 py-3">
      <div className="flex justify-between items-center mb-3">
        <label className="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-gray-300">
          <Server size={18} className="text-gray-600 dark:text-gray-400" />
          Servers
        </label>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleAdd}
          disabled={!selectedVersionId}
          className="text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20"
        >
          <Plus size={14} />
          Add
        </Button>
      </div>
      <p className="text-[11px] text-gray-500 dark:text-gray-400 -mt-1 mb-2">
        Define multiple server URLs (e.g. Production, Staging). Exported in the OpenAPI spec.
      </p>

      {!selectedVersionId ? (
        <p className="text-xs text-gray-500 dark:text-gray-400">Select a version to manage servers.</p>
      ) : isLoading ? (
        <span className="text-xs text-gray-500 dark:text-gray-400">Loading...</span>
      ) : servers.length === 0 ? (
        <div
          className={
            'py-6 px-4 text-center rounded-lg border border-dashed ' +
            (isDark ? 'border-slate-600' : 'border-slate-300')
          }
        >
          <Server size={32} className={`mx-auto mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`} />
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">No servers defined</p>
          <Button variant="outline" size="sm" onClick={handleAdd} className="border-indigo-500 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20">
            <Plus size={14} />
            Add server
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {servers.map((server) => (
            <div
              key={server.id}
              className={
                'p-3 rounded-lg border flex justify-between items-center ' +
                (isDark ? 'border-slate-700 bg-slate-900/50' : 'border-slate-200 bg-slate-50')
              }
            >
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-gray-900 dark:text-white block truncate flex items-center gap-1.5">
                  {server.name || server.url || 'Server'}
                  {server.environment && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-600 text-slate-700 dark:text-slate-300">
                      {server.environment === 'prod' ? 'Production' : server.environment === 'staging' ? 'Staging' : server.environment === 'dev' ? 'Development' : server.environment}
                    </span>
                  )}
                </span>
                <span className="text-[11px] text-gray-500 dark:text-gray-400 block truncate" title={server.url}>
                  {server.url}
                </span>
                {server.description && (
                  <span className="text-[11px] text-gray-500 dark:text-gray-400 block truncate mt-0.5">
                    {server.description}
                  </span>
                )}
                {server.variables && Object.keys(server.variables).length > 0 && (
                  <span className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5 block">
                    Variables: {Object.keys(server.variables).join(', ')}
                  </span>
                )}
              </div>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => handleEdit(server)}
                  className="text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                >
                  <Pencil size={14} />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => handleDelete(server)}
                  className="text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20"
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog.Root open={dialogOpen} onOpenChange={(open) => { setDialogOpen(open); if (!open) resetForm(); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[9999] w-full max-w-md max-h-[90vh] flex flex-col rounded-xl shadow-xl p-6 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 overflow-y-auto"
            onPointerDownOutside={(e) => e.preventDefault()}
          >
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              {editingServer ? 'Edit Server' : 'Add Server'}
            </Dialog.Title>
            {formError && (
              <div
                className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-sm text-red-700 dark:text-red-300"
                role="alert"
              >
                {formError}
              </div>
            )}
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="server-name">Name (optional)</Label>
                <Input
                  id="server-name"
                  placeholder="e.g. Production, Staging"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="server-url">URL (required)</Label>
                <Input
                  id="server-url"
                  placeholder="https://api.example.com or /api/v1"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                <p className="text-[11px] text-gray-500 dark:text-gray-400">
                  Absolute (https://...) or relative (/api/v1) paths allowed.
                </p>
              </div>
              <div className="space-y-2">
                <Label>Environment (optional)</Label>
                <Select value={environment} onValueChange={setEnvironment}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select environment" />
                  </SelectTrigger>
                  <SelectContent className="z-[10001]">
                    {ENVIRONMENT_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="server-description">Description (optional)</Label>
                <Textarea
                  id="server-description"
                  placeholder="e.g. Production API server"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>Server variables (optional)</Label>
                  <Button variant="ghost" size="sm" onClick={addVariable} className="text-indigo-600 dark:text-indigo-400 text-xs h-8">
                    <Plus size={12} />
                    Add variable
                  </Button>
                </div>
                <p className="text-[11px] text-gray-500 dark:text-gray-400">
                  Use in URL as {'{variableName}'}. OpenAPI: default, enum, description.
                </p>
                {variables.length > 0 && (
                  <div className="flex flex-col gap-2">
                    {variables.map((v) => (
                      <div
                        key={v.id}
                        className={
                          'p-3 rounded-lg border flex flex-col gap-2 ' +
                          (isDark ? 'border-slate-700 bg-slate-900/50' : 'border-slate-200 bg-slate-50')
                        }
                      >
                        <div className="flex gap-2 items-center">
                          <Input
                            placeholder="Name"
                            value={v.name}
                            onChange={(e) => updateVariable(v.id, 'name', e.target.value)}
                            className="flex-1 h-9 text-xs"
                          />
                          <Input
                            placeholder="Default"
                            value={v.default}
                            onChange={(e) => updateVariable(v.id, 'default', e.target.value)}
                            className="flex-1 h-9 text-xs"
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => removeVariable(v.id)}
                            className="shrink-0 h-9 w-9 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                          >
                            <Trash2 size={14} />
                          </Button>
                        </div>
                        <Input
                          placeholder="Enum (comma-separated)"
                          value={v.enum}
                          onChange={(e) => updateVariable(v.id, 'enum', e.target.value)}
                          className="h-9 text-xs"
                        />
                        <Input
                          placeholder="Variable description"
                          value={v.description}
                          onChange={(e) => updateVariable(v.id, 'description', e.target.value)}
                          className="h-9 text-xs"
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <Dialog.Close asChild>
                <Button variant="secondary" type="button">
                  Cancel
                </Button>
              </Dialog.Close>
              <Button
                type="button"
                onClick={handleSave}
                disabled={isSaving || !url?.trim()}
              >
                {isSaving ? 'Saving...' : editingServer ? 'Save' : 'Add'}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

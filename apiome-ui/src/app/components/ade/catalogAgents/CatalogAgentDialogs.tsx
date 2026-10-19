'use client';

/**
 * **Register agent** and **Add model** — CDG-5.2 (#5980).
 *
 * Opened from the catalog home when the Kind facet is Agents or Models. Registering an agent with
 * keys makes it a consumer of every project those keys' toolsets reach; the dialog lists the
 * workspace's live agent keys by name and prefix only — never a secret. Both dialogs reuse the
 * Agent Access form classes (`agx-*`).
 */

import * as React from 'react';
import { Alert, Button, Checkbox, Input, Label, Textarea } from '@/app/components/ui';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import {
  MODEL_HOSTINGS,
  MODEL_HOSTING_LABELS,
  type CatalogAgent,
  type CatalogModel,
  type ModelHosting,
} from '@lib/catalog-agents';
import {
  createAgent,
  createModel,
  fetchAgentKeys,
  fetchModels,
  type LinkableKey,
} from './catalogAgentsApi';

/** Props shared by both dialogs. */
interface CreateDialogProps<T> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with what was created. */
  onCreated: (created: T) => void;
}

/**
 * Register an agent: name, runtime, description, model and the agent keys it uses.
 *
 * @param props - Open state and the created callback.
 * @returns The dialog.
 */
export function RegisterAgentDialog({ open, onOpenChange, onCreated }: CreateDialogProps<CatalogAgent>) {
  const [name, setName] = React.useState('');
  const [runtime, setRuntime] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [model, setModel] = React.useState('');
  const [keyIds, setKeyIds] = React.useState<string[]>([]);
  const [models, setModels] = React.useState<CatalogModel[]>([]);
  const [keys, setKeys] = React.useState<LinkableKey[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [touched, setTouched] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setName('');
    setRuntime('');
    setDescription('');
    setModel('');
    setKeyIds([]);
    setError(null);
    setTouched(false);
    fetchModels().then(setModels).catch(() => setModels([]));
    fetchAgentKeys().then(setKeys).catch(() => setKeys([]));
  }, [open]);

  const nameMissing = !name.trim();

  const submit = async () => {
    setTouched(true);
    if (nameMissing) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createAgent({
        name: name.trim(),
        runtime: runtime.trim() || undefined,
        description: description.trim() || undefined,
        model: model || null,
        keyIds,
      });
      onOpenChange(false);
      onCreated(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not register the agent');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="register-agent-dialog">
        <DialogHeader>
          <DialogTitle>Register agent</DialogTitle>
          <DialogDescription>
            The agent becomes a consumer of every project its keys reach.
          </DialogDescription>
        </DialogHeader>
        <form
          className="agx-form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          {error ? <Alert variant="error">{error}</Alert> : null}
          <div className="agx-field">
            <Label htmlFor="agent-name">Name</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-invalid={touched && nameMissing ? true : undefined}
              aria-describedby={touched && nameMissing ? 'agent-name-problem' : undefined}
              data-testid="register-agent-name"
            />
            {touched && nameMissing ? (
              <p id="agent-name-problem" className="agt-problem">
                Enter a name, for example Support bot.
              </p>
            ) : null}
          </div>
          <div className="agx-field">
            <Label htmlFor="agent-runtime">Runtime</Label>
            <Input
              id="agent-runtime"
              value={runtime}
              placeholder="LangGraph, Claude Desktop, a Lambda…"
              onChange={(event) => setRuntime(event.target.value)}
              data-testid="register-agent-runtime"
            />
          </div>
          <div className="agx-field">
            <Label htmlFor="agent-model">Model</Label>
            <select
              id="agent-model"
              className="hive-control agx-select"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              data-testid="register-agent-model"
            >
              <option value="">No model</option>
              {models.map((entry) => (
                <option key={entry.id} value={entry.slug}>
                  {entry.name} · {entry.provider}
                </option>
              ))}
            </select>
          </div>
          <div className="agx-field">
            <Label htmlFor="agent-description">Description</Label>
            <Textarea
              id="agent-description"
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <fieldset className="agx-field agt-keys-field">
            <legend className="agx-legend">Agent keys</legend>
            {keys.length === 0 ? (
              <p className="agx-hint">No live agent keys yet. Create one under MCP servers → Agent access.</p>
            ) : (
              keys.map((key) => (
                <label key={key.id} className="agt-key-option">
                  <Checkbox
                    checked={keyIds.includes(key.id)}
                    onCheckedChange={(checked) =>
                      setKeyIds((current) =>
                        checked === true ? [...current, key.id] : current.filter((id) => id !== key.id),
                      )
                    }
                    data-testid={`register-agent-key-${key.id}`}
                  />
                  <span>{key.name}</span>
                  <span className="agt-muted mono">{key.keyPrefix}</span>
                </label>
              ))
            )}
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy} data-testid="register-agent-submit">
              {busy ? 'Registering…' : 'Register agent'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Add a model: provider, model name and version, hosting, data handling, deprecation date.
 *
 * @param props - Open state and the created callback.
 * @returns The dialog.
 */
export function AddModelDialog({ open, onOpenChange, onCreated }: CreateDialogProps<CatalogModel>) {
  const [provider, setProvider] = React.useState('');
  const [modelName, setModelName] = React.useState('');
  const [modelVersion, setModelVersion] = React.useState('');
  const [hosting, setHosting] = React.useState<ModelHosting>('api');
  const [dataHandling, setDataHandling] = React.useState('');
  const [deprecatedAt, setDeprecatedAt] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [touched, setTouched] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setProvider('');
    setModelName('');
    setModelVersion('');
    setHosting('api');
    setDataHandling('');
    setDeprecatedAt('');
    setError(null);
    setTouched(false);
  }, [open]);

  const missing = !provider.trim() || !modelName.trim();

  const submit = async () => {
    setTouched(true);
    if (missing) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createModel({
        provider: provider.trim(),
        modelName: modelName.trim(),
        modelVersion: modelVersion.trim() || undefined,
        hosting,
        dataHandling: dataHandling.trim() || undefined,
        deprecatedAt: deprecatedAt ? new Date(`${deprecatedAt}T00:00:00Z`).toISOString() : null,
      });
      onOpenChange(false);
      onCreated(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not register the model');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="add-model-dialog">
        <DialogHeader>
          <DialogTitle>Add model</DialogTitle>
          <DialogDescription>Record a model your agents run on, and how it handles data.</DialogDescription>
        </DialogHeader>
        <form
          className="agx-form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          {error ? <Alert variant="error">{error}</Alert> : null}
          {touched && missing ? (
            <p className="agt-problem" role="alert">
              Enter the provider and the model name.
            </p>
          ) : null}
          <div className="agx-field">
            <Label htmlFor="model-provider">Provider</Label>
            <Input
              id="model-provider"
              value={provider}
              placeholder="Anthropic, OpenAI, an internal team…"
              onChange={(event) => setProvider(event.target.value)}
              data-testid="add-model-provider"
            />
          </div>
          <div className="agx-field">
            <Label htmlFor="model-name">Model name</Label>
            <Input
              id="model-name"
              value={modelName}
              onChange={(event) => setModelName(event.target.value)}
              data-testid="add-model-name"
            />
          </div>
          <div className="agx-field">
            <Label htmlFor="model-version">Version</Label>
            <Input id="model-version" value={modelVersion} onChange={(event) => setModelVersion(event.target.value)} />
          </div>
          <div className="agx-field">
            <Label htmlFor="model-hosting">Hosting</Label>
            <select
              id="model-hosting"
              className="hive-control agx-select"
              value={hosting}
              onChange={(event) => setHosting(event.target.value as ModelHosting)}
              data-testid="add-model-hosting"
            >
              {MODEL_HOSTINGS.map((value) => (
                <option key={value} value={value}>
                  {MODEL_HOSTING_LABELS[value]}
                </option>
              ))}
            </select>
          </div>
          <div className="agx-field">
            <Label htmlFor="model-data">Data handling</Label>
            <Textarea
              id="model-data"
              rows={3}
              value={dataHandling}
              placeholder="What the provider retains, where data is processed, training opt-outs."
              onChange={(event) => setDataHandling(event.target.value)}
            />
          </div>
          <div className="agx-field">
            <Label htmlFor="model-deprecated">Deprecated on</Label>
            <Input
              id="model-deprecated"
              type="date"
              value={deprecatedAt}
              onChange={(event) => setDeprecatedAt(event.target.value)}
              data-testid="add-model-deprecated"
            />
            <p className="agx-hint">Shown on every agent that runs on this model.</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy} data-testid="add-model-submit">
              {busy ? 'Adding…' : 'Add model'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

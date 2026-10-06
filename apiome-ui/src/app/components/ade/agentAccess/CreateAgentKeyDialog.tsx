'use client';

import * as React from 'react';
import { KeyRound } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Spinner } from '@/app/components/ui/Spinner';
import { Textarea } from '@/app/components/ui/Textarea';

import {
  allowableToolNames,
  toolsetLabel,
  validateAgentKeyDraft,
  EMPTY_AGENT_KEY_DRAFT,
  type AgentKeyDraft,
  type AgentToolset,
  type AgentToolsetDetail,
  type PublishedVersionOption,
} from './agentAccessModel';
import ToolChecklist from './ToolChecklist';

/**
 * Create an agent key — AGX-3.4 (#4540), over AGX-3.1.
 *
 * Name, description, the toolset it is bound to, the tools it may call (the toolset's enabled
 * tools, all pre-selected) and an optional expiry in days. Expiry is set here once: apiome-rest
 * has no call to change it later, so the dialog says that changing it means a new key.
 *
 * The secret is not this dialog's: on success the page opens the reveal-once dialog.
 */

/** Props for {@link CreateAgentKeyDialog}. */
export interface CreateAgentKeyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  toolsets: readonly AgentToolset[];
  versions: readonly PublishedVersionOption[];
  /** The toolset to start on, e.g. when opened from the toolset editor. */
  initialToolsetId: string | null;
  /**
   * Load a toolset's tools (to offer them as the allowlist).
   *
   * @throws when they cannot be read.
   */
  loadToolset: (toolsetId: string) => Promise<AgentToolsetDetail>;
  /**
   * Create the key.
   *
   * @returns `null` on success, or the message to show.
   */
  onSubmit: (draft: AgentKeyDraft) => Promise<string | null>;
}

/** Field id prefix; one instance is mounted at a time. */
const FIELD_ID = 'agx-key';

/**
 * The dialog.
 *
 * @param props See {@link CreateAgentKeyDialogProps}.
 * @returns The dialog.
 */
export default function CreateAgentKeyDialog({
  open,
  onOpenChange,
  toolsets,
  versions,
  initialToolsetId,
  loadToolset,
  onSubmit,
}: CreateAgentKeyDialogProps) {
  const [draft, setDraft] = React.useState<AgentKeyDraft>(EMPTY_AGENT_KEY_DRAFT);
  const [choices, setChoices] = React.useState<string[]>([]);
  const [toolsLoading, setToolsLoading] = React.useState(false);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setDraft({ ...EMPTY_AGENT_KEY_DRAFT, toolsetId: initialToolsetId ?? toolsets[0]?.id ?? '' });
    setError('');
    setBusy(false);
    // Only on opening: the toolset list refreshing underneath must not reset what was typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Whenever the chosen toolset changes, offer its enabled tools — all selected, because the
  // common case is "this agent may use what the toolset exposes".
  React.useEffect(() => {
    if (!open || !draft.toolsetId) {
      setChoices([]);
      return;
    }
    let cancelled = false;
    setToolsLoading(true);
    loadToolset(draft.toolsetId)
      .then((toolset) => {
        if (cancelled) return;
        const names = allowableToolNames(toolset);
        setChoices(names);
        setDraft((current) => ({ ...current, toolAllowlist: names }));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setChoices([]);
        setError(err instanceof Error ? err.message : 'Failed to load the toolset’s tools');
      })
      .finally(() => {
        if (!cancelled) setToolsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, draft.toolsetId, loadToolset]);

  const update = React.useCallback((patch: Partial<AgentKeyDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
  }, []);

  const submit = React.useCallback(async () => {
    const invalid = validateAgentKeyDraft(draft);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    setError('');
    const failure = await onSubmit(draft);
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  }, [draft, onOpenChange, onSubmit]);

  const disabled = busy || toolsLoading;

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="agx-key-create-dialog">
        <DialogHeader>
          <DialogTitle className="agx-dialog-title">
            <span className="tnt-icon-tile" data-tone="honey">
              <KeyRound aria-hidden />
            </span>
            Create agent key
          </DialogTitle>
          <DialogDescription>
            The credential an AI agent presents to Apiome&apos;s MCP endpoint.
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
          {error && (
            <Alert variant="error" data-testid="agx-key-create-error">
              {error}
            </Alert>
          )}

          <div className="agx-field">
            <Label htmlFor={`${FIELD_ID}-name`}>
              Name <span aria-hidden="true">*</span>
            </Label>
            <Input
              id={`${FIELD_ID}-name`}
              value={draft.name}
              placeholder="claude-desktop"
              required
              autoFocus
              disabled={busy}
              onChange={(event) => update({ name: event.target.value })}
            />
          </div>

          <div className="agx-field">
            <Label htmlFor={`${FIELD_ID}-description`}>Description</Label>
            <Textarea
              id={`${FIELD_ID}-description`}
              value={draft.description}
              placeholder="Which agent holds this key?"
              rows={2}
              disabled={busy}
              onChange={(event) => update({ description: event.target.value })}
            />
          </div>

          <div className="agx-field">
            <Label htmlFor={`${FIELD_ID}-toolset`}>Toolset</Label>
            <select
              id={`${FIELD_ID}-toolset`}
              className="hive-control agx-select"
              value={draft.toolsetId}
              disabled={busy}
              onChange={(event) => update({ toolsetId: event.target.value, toolAllowlist: [] })}
            >
              {toolsets.map((t) => (
                <option key={t.id} value={t.id}>
                  {toolsetLabel(t, versions)}
                </option>
              ))}
            </select>
          </div>

          <div className="agx-field">
            <span className="agx-legend" id={`${FIELD_ID}-tools`}>
              Tools this key may call
            </span>
            {toolsLoading ? (
              <span className="agx-hint">Loading tools…</span>
            ) : (
              <ToolChecklist
                choices={choices}
                value={draft.toolAllowlist}
                onChange={(toolAllowlist) => update({ toolAllowlist })}
                disabled={busy}
                labelledBy={`${FIELD_ID}-tools`}
                idPrefix={`${FIELD_ID}-tool`}
              />
            )}
          </div>

          <div className="agx-field agx-expiry-field">
            <Label htmlFor={`${FIELD_ID}-expiry`}>Expires in (days)</Label>
            <Input
              id={`${FIELD_ID}-expiry`}
              type="number"
              min={1}
              step={1}
              value={draft.expiresInDays}
              placeholder="Never"
              disabled={busy}
              onChange={(event) => update({ expiresInDays: event.target.value })}
            />
            <p className="agx-hint">
              Leave empty for no expiry. Expiry cannot be changed later; revoke and create a new
              key instead.
            </p>
          </div>
        </form>

        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={disabled || toolsets.length === 0}
            data-testid="agx-key-create-submit"
            onClick={() => void submit()}
          >
            {busy ? <Spinner size="sm" aria-hidden /> : <KeyRound aria-hidden />}
            {busy ? 'Creating…' : 'Create agent key'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

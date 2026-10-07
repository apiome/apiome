'use client';

import * as React from 'react';
import { ListChecks } from 'lucide-react';

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
import { Spinner } from '@/app/components/ui/Spinner';

import {
  allowableToolNames,
  allowlistChanged,
  inactiveAllowlistEntries,
  type AgentKey,
  type AgentToolsetDetail,
} from './agentAccessModel';
import ToolChecklist from './ToolChecklist';

/**
 * Edit an agent key's tool allowlist — AGX-3.4 (#4540), over AGX-3.1's
 * `PUT /agent-keys/{id}/allowlist`.
 *
 * The MCP runtime reads the allowlist on every request, so the change applies to the agent's next
 * `tools/list` / `tools/call`. Saving is offered only when the selection actually differs.
 */

/** Props for {@link AllowlistDialog}. */
export interface AllowlistDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The key being edited. */
  agentKey: AgentKey | null;
  /**
   * Load the key's toolset with its tools.
   *
   * @throws when it cannot be read.
   */
  loadToolset: (toolsetId: string) => Promise<AgentToolsetDetail>;
  /**
   * Save the new allowlist.
   *
   * @returns `null` on success, or the message to show.
   */
  onSubmit: (key: AgentKey, toolAllowlist: string[]) => Promise<string | null>;
}

/**
 * The dialog.
 *
 * @param props See {@link AllowlistDialogProps}.
 * @returns The dialog.
 */
export default function AllowlistDialog({
  open,
  onOpenChange,
  agentKey,
  loadToolset,
  onSubmit,
}: AllowlistDialogProps) {
  const [toolset, setToolset] = React.useState<AgentToolsetDetail | null>(null);
  const [value, setValue] = React.useState<string[]>([]);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!open || !agentKey) return;
    let cancelled = false;
    setValue([...agentKey.toolAllowlist].sort());
    setToolset(null);
    setError('');
    setBusy(false);
    setLoading(true);
    loadToolset(agentKey.toolsetId)
      .then((loaded) => {
        if (!cancelled) setToolset(loaded);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load the toolset’s tools. Refresh the page to try again.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, agentKey, loadToolset]);

  const changed = agentKey ? allowlistChanged(agentKey.toolAllowlist, value) : false;

  const submit = React.useCallback(async () => {
    if (!agentKey) return;
    if (value.length === 0) {
      setError('Allow at least one tool — a key with an empty allowlist can call nothing.');
      return;
    }
    setBusy(true);
    setError('');
    const failure = await onSubmit(agentKey, value);
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  }, [agentKey, onOpenChange, onSubmit, value]);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="agx-allowlist-dialog">
        <DialogHeader>
          <DialogTitle className="agx-dialog-title">
            <span className="tnt-icon-tile" data-tone="accent">
              <ListChecks aria-hidden />
            </span>
            Tools for {agentKey?.name ?? 'this key'}
          </DialogTitle>
          <DialogDescription>
            The agent&apos;s next request sees the new list. A tool must also be exposed by the
            toolset to be callable.
          </DialogDescription>
        </DialogHeader>

        <div className="agx-form">
          {error && (
            <Alert variant="error" data-testid="agx-allowlist-error">
              {error}
            </Alert>
          )}
          <span className="agx-legend" id="agx-allowlist-tools">
            Allowed tools
          </span>
          {loading || !toolset ? (
            <span className="agx-hint">{loading ? 'Loading tools…' : ''}</span>
          ) : (
            <ToolChecklist
              choices={allowableToolNames(toolset)}
              inactive={inactiveAllowlistEntries(agentKey?.toolAllowlist ?? [], toolset)}
              value={value}
              onChange={setValue}
              disabled={busy}
              labelledBy="agx-allowlist-tools"
              idPrefix="agx-allowlist-tool"
            />
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={busy || loading || !changed}
            data-testid="agx-allowlist-save"
            onClick={() => void submit()}
          >
            {busy && <Spinner size="sm" aria-hidden />}
            {busy ? 'Saving…' : 'Save tools'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

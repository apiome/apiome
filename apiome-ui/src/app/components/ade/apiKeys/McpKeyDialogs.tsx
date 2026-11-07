'use client';

import * as React from 'react';
import { Ban, KeyRound } from 'lucide-react';

import type { McpApiKeyMetadata } from '@/app/ade/dashboard/tenants/mcpKeysApi';
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

import { displayApiKeyPrefix } from './apiKeysModel';
import { EMPTY_MCP_KEY_DRAFT, validateMcpKeyDraft, type McpKeyDraft } from './mcpKeysModel';

/**
 * The MCP tab's create form and revoke confirm.
 *
 * Both follow the REST tab's dialogs ({@link ./CreateApiKeyDialog},
 * {@link ./ApiKeyLifecycleDialogs}): a failed write is shown inline beside the button that
 * caused it, and the dialog cannot be dismissed while the write runs. The one-time reveal is
 * the REST tab's own {@link ./ApiKeySecretDialog}, retitled — the secret has the same life.
 */

/** The id prefix the create form's fields hang their labels from. */
const FIELD_ID = 'mcp-key-create';

/** Props for {@link CreateMcpKeyDialog}. */
export interface CreateMcpKeyDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /**
   * Create the key.
   *
   * @param draft What was typed.
   * @returns The error to show inline, or `null` on success.
   */
  onSubmit: (draft: McpKeyDraft) => Promise<string | null>;
}

/**
 * Create an MCP key — a label and an optional expiry.
 *
 * What the key may call is not chosen here: a new key inherits the workspace's MCP defaults,
 * and a custom set is edited under the workspace's Per-key capabilities.
 *
 * @param props See {@link CreateMcpKeyDialogProps}.
 * @returns The dialog.
 */
export function CreateMcpKeyDialog({ open, onOpenChange, onSubmit }: CreateMcpKeyDialogProps) {
  const [draft, setDraft] = React.useState<McpKeyDraft>(EMPTY_MCP_KEY_DRAFT);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  // Opening resets the form, as in the REST dialog, so a refused write keeps what was typed.
  React.useEffect(() => {
    if (!open) return;
    setDraft(EMPTY_MCP_KEY_DRAFT);
    setError('');
    setBusy(false);
  }, [open]);

  const submit = React.useCallback(async () => {
    const invalid = validateMcpKeyDraft(draft);
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

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="mcp-key-create-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="tnt-icon-tile" data-tone="honey">
              <KeyRound aria-hidden />
            </span>
            Create MCP key
          </DialogTitle>
          <DialogDescription>
            Create a key for an MCP host or agent calling Apiome&apos;s MCP server.
          </DialogDescription>
        </DialogHeader>

        <form
          className="akey-form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          {error && (
            <Alert variant="error" data-testid="mcp-key-create-error">
              {error}
            </Alert>
          )}

          <div className="akey-field">
            <Label htmlFor={`${FIELD_ID}-label`}>
              Label <span aria-hidden="true">*</span>
            </Label>
            <Input
              id={`${FIELD_ID}-label`}
              value={draft.label}
              placeholder="Claude Desktop"
              required
              autoFocus
              disabled={busy}
              onChange={(event) => setDraft((current) => ({ ...current, label: event.target.value }))}
            />
            <p className="akey-field__hint">Which host or agent uses this key</p>
          </div>

          <div className="akey-field akey-expiry-field">
            <Label htmlFor={`${FIELD_ID}-expiry`}>Expires in (days)</Label>
            <Input
              id={`${FIELD_ID}-expiry`}
              type="number"
              min={1}
              step={1}
              value={draft.expiresInDays}
              placeholder="Leave empty for no expiration"
              disabled={busy}
              onChange={(event) =>
                setDraft((current) => ({ ...current, expiresInDays: event.target.value }))
              }
            />
            <p className="akey-field__hint">Leave empty for no expiration.</p>
          </div>
        </form>

        <DialogFooter>
          <span className="akey-dialog-note">
            New keys call the workspace&apos;s default MCP tools.
          </span>
          <Button
            variant="outline"
            disabled={busy}
            title={busy ? 'Wait for the key to be created' : undefined}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            disabled={busy}
            title={busy ? 'Creating the key' : undefined}
            data-testid="mcp-key-create-submit"
            onClick={() => void submit()}
          >
            {busy ? <Spinner size="sm" aria-hidden /> : <KeyRound aria-hidden />}
            {busy ? 'Creating…' : 'Create MCP key'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Props for {@link RevokeMcpKeyDialog}. */
export interface RevokeMcpKeyDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** The key the dialog is about; `null` while it is closed. */
  mcpKey: McpApiKeyMetadata | null;
  /**
   * Revoke the key.
   *
   * @param key The key.
   * @returns The error to show inline, or `null` on success.
   */
  onConfirm: (key: McpApiKeyMetadata) => Promise<string | null>;
}

/**
 * Revoke an MCP key — permanent; the row stays in the list as Revoked.
 *
 * @param props See {@link RevokeMcpKeyDialogProps}.
 * @returns The dialog.
 */
export function RevokeMcpKeyDialog({ open, onOpenChange, mcpKey, onConfirm }: RevokeMcpKeyDialogProps) {
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setError('');
    setBusy(false);
  }, [open]);

  const run = React.useCallback(async () => {
    if (!mcpKey) return;
    setBusy(true);
    setError('');
    const failure = await onConfirm(mcpKey);
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  }, [mcpKey, onConfirm, onOpenChange]);

  const label = mcpKey?.label ?? 'this MCP key';

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent size="sm" role="alertdialog" data-testid="mcp-key-revoke-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="tnt-icon-tile" data-tone="danger">
              <Ban aria-hidden />
            </span>
            Revoke MCP key
          </DialogTitle>
          <DialogDescription>
            Are you sure you want to revoke “{label}”? This action cannot be undone.
          </DialogDescription>
        </DialogHeader>

        <div className="akey-confirm-body">
          {mcpKey && (
            <span className="akey-confirm-identity">
              <span className="akey-confirm-identity__name">{mcpKey.label}</span>
              <code className="mono akey-confirm-identity__prefix">
                {displayApiKeyPrefix(mcpKey.prefix)}
              </code>
            </span>
          )}
          <Alert variant="danger" data-testid="mcp-key-revoke-warning">
            Every MCP host or agent using this key is refused from its next call. The key stays
            in the list as Revoked.
          </Alert>
          {error && <Alert variant="error">{error}</Alert>}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={busy}
            title={busy ? 'Wait for the key to be revoked' : undefined}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            title={busy ? 'Revoking the key' : undefined}
            data-testid="mcp-key-revoke-confirm"
            onClick={() => void run()}
          >
            {busy ? <Spinner size="sm" aria-hidden /> : <Ban aria-hidden />}
            {busy ? 'Revoking…' : 'Revoke'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

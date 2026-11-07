'use client';

import * as React from 'react';
import { RefreshCw } from 'lucide-react';

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

import { displayApiKeyPrefix } from './apiKeysModel';
import { WORKSPACE_KEY_KIND_LABEL, type WorkspaceKeyKind } from './workspaceKeysModel';

/**
 * Regenerate a key — replace its secret in place.
 *
 * The confirm before the secret of a REST or an MCP key is rolled: the key keeps its id, name,
 * scopes or tools and expiry, and only the secret changes. That is the cheap way out of a leaked
 * or lost secret — no new key to create, name and scope again — and the cost is stated before
 * the button: every caller still holding the old secret is refused from its next request.
 *
 * The new secret is not shown here. On success the caller closes this dialog and opens the
 * reveal-once dialog with it, the same one a newly created key goes through.
 */

/** The key the dialog is about. */
export interface RegenerateKeyTarget {
  /** Which kind of key, for the copy. */
  kind: WorkspaceKeyKind;
  /** Its name or label. */
  name: string;
  /** Its stored prefix — the one about to stop working. */
  prefix: string;
}

/** Props for {@link RegenerateKeyDialog}. */
export interface RegenerateKeyDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** The key; `null` while closed. */
  target: RegenerateKeyTarget | null;
  /**
   * Regenerate the key.
   *
   * @returns The error to show inline, or `null` on success.
   */
  onConfirm: () => Promise<string | null>;
}

/**
 * The regenerate confirm.
 *
 * @param props See {@link RegenerateKeyDialogProps}.
 * @returns The dialog.
 */
export default function RegenerateKeyDialog({
  open,
  onOpenChange,
  target,
  onConfirm,
}: RegenerateKeyDialogProps) {
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setError('');
    setBusy(false);
  }, [open]);

  const run = React.useCallback(async () => {
    setBusy(true);
    setError('');
    const failure = await onConfirm();
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  }, [onConfirm, onOpenChange]);

  const name = target?.name ?? 'this key';
  const kept = target?.kind === 'mcp' ? 'tools' : 'scopes';
  const callers = target?.kind === 'mcp' ? 'MCP host or agent' : 'caller';

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent size="sm" role="alertdialog" data-testid="key-regenerate-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="tnt-icon-tile" data-tone="warn">
              <RefreshCw aria-hidden />
            </span>
            Regenerate {target ? WORKSPACE_KEY_KIND_LABEL[target.kind] : ''} key
          </DialogTitle>
          <DialogDescription>
            Replace the secret of “{name}”? Its name, {kept} and expiry stay the same.
          </DialogDescription>
        </DialogHeader>

        <div className="akey-confirm-body">
          {target && (
            <span className="akey-confirm-identity">
              <span className="akey-confirm-identity__name">{target.name}</span>
              <code className="mono akey-confirm-identity__prefix">
                {displayApiKeyPrefix(target.prefix)}
              </code>
            </span>
          )}
          <Alert variant="warn" data-testid="key-regenerate-warning">
            The current secret stops working immediately: every {callers} using it is refused
            from its next request. You&apos;ll see the new secret once — put it wherever the old one
            is stored.
          </Alert>
          {error && <Alert variant="error">{error}</Alert>}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={busy}
            title={busy ? 'Wait for the key to be regenerated' : undefined}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            disabled={busy}
            title={busy ? 'Regenerating the key' : undefined}
            data-testid="key-regenerate-confirm"
            onClick={() => void run()}
          >
            {busy ? <Spinner size="sm" aria-hidden /> : <RefreshCw aria-hidden />}
            {busy ? 'Regenerating…' : 'Regenerate'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

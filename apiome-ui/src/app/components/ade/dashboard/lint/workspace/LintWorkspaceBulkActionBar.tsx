'use client';

/**
 * Bulk action bar for the workspace queue (CLX-4.1, #4859).
 *
 * Appears when the selection is non-empty: assign owner, acknowledge, mark fixed /
 * false-positive, request a waiver (rationale dialog), and approve / reject requested
 * waivers. Actions that need lint_findings:publish render for everyone — the server is the
 * authority and per-item errors surface in the result toast. After an applied bulk action
 * the page offers Undo built from the response's beforeStates.
 */

import React, { useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Textarea,
} from '@/app/components/ui';
import type { BulkActionSet } from '@/app/utils/lint-workspace';
import type { LintDecisionState } from '@/app/utils/lint-policy-ui';

export interface LintWorkspaceBulkActionBarProps {
  selectedCount: number;
  busy?: boolean;
  onApply: (set: BulkActionSet) => void;
  onClearSelection: () => void;
}

type WaiverDialogMode = 'request' | 'approve' | null;

/** Sticky action bar shown while findings are selected. */
export default function LintWorkspaceBulkActionBar({
  selectedCount,
  busy,
  onApply,
  onClearSelection,
}: LintWorkspaceBulkActionBarProps) {
  const [waiverMode, setWaiverMode] = useState<WaiverDialogMode>(null);
  const [rationale, setRationale] = useState('');
  const [linkedTicket, setLinkedTicket] = useState('');
  const [expiresAt, setExpiresAt] = useState('');
  const [owner, setOwner] = useState('');

  if (selectedCount === 0) return null;

  const simpleAction = (state: LintDecisionState) => onApply({ state });

  const submitWaiverDialog = () => {
    const set: BulkActionSet = {
      state: waiverMode === 'approve' ? 'waived' : 'waiver_requested',
      rationale: rationale.trim(),
    };
    if (linkedTicket.trim()) set.linkedTicket = linkedTicket.trim();
    if (expiresAt) set.expiresAt = new Date(expiresAt).toISOString();
    onApply(set);
    setWaiverMode(null);
    setRationale('');
    setLinkedTicket('');
    setExpiresAt('');
  };

  return (
    <div
      data-testid="lint-workspace-bulk-bar"
      className="sticky bottom-2 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 shadow-sm dark:border-indigo-800 dark:bg-indigo-950/60"
    >
      <span className="text-sm font-medium text-indigo-900 dark:text-indigo-200">
        {selectedCount} selected
      </span>
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-acknowledge"
        disabled={busy}
        onClick={() => simpleAction('acknowledged')}
      >
        Acknowledge
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-fixed"
        disabled={busy}
        onClick={() => simpleAction('fixed')}
      >
        Mark fixed
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-false-positive"
        disabled={busy}
        onClick={() => simpleAction('false_positive')}
      >
        False positive
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-request-waiver"
        disabled={busy}
        onClick={() => setWaiverMode('request')}
      >
        Request waiver
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-approve-waiver"
        disabled={busy}
        onClick={() => setWaiverMode('approve')}
        title="Requires waiver approval permission (lint_findings:publish)"
      >
        Approve waiver
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="bulk-reject-waiver"
        disabled={busy}
        onClick={() => simpleAction('open')}
        title="Reopen — also rejects requested waivers (requires approval permission)"
      >
        Reopen / reject
      </Button>
      <span className="mx-1 h-5 w-px bg-indigo-200 dark:bg-indigo-800" />
      <div className="flex items-center gap-1">
        <Input
          data-testid="bulk-owner-input"
          placeholder="Assign owner (user id)"
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          className="h-7 w-44 text-xs"
        />
        <Button
          size="sm"
          variant="outline"
          data-testid="bulk-assign-owner"
          disabled={busy || !owner.trim()}
          onClick={() => {
            onApply({ ownerUserId: owner.trim() });
            setOwner('');
          }}
        >
          Assign
        </Button>
      </div>
      <button
        type="button"
        data-testid="bulk-clear-selection"
        className="ml-auto text-xs font-medium text-indigo-700 hover:underline dark:text-indigo-300"
        onClick={onClearSelection}
      >
        Clear selection
      </button>

      <Dialog open={waiverMode !== null} onOpenChange={(open) => !open && setWaiverMode(null)}>
        <DialogContent data-testid="waiver-dialog">
          <DialogHeader>
            <DialogTitle>
              {waiverMode === 'approve'
                ? `Approve waiver for ${selectedCount} finding${selectedCount === 1 ? '' : 's'}`
                : `Request waiver for ${selectedCount} finding${selectedCount === 1 ? '' : 's'}`}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="waiver-rationale">Rationale (required)</Label>
              <Textarea
                id="waiver-rationale"
                data-testid="waiver-rationale"
                value={rationale}
                onChange={(e) => setRationale(e.target.value)}
                placeholder="Why is this finding acceptable?"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="waiver-ticket">Linked ticket (optional)</Label>
              <Input
                id="waiver-ticket"
                data-testid="waiver-ticket"
                value={linkedTicket}
                onChange={(e) => setLinkedTicket(e.target.value)}
                placeholder="https://tracker/TICKET-123"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="waiver-expires">
                Expires {waiverMode === 'approve' ? '(required)' : '(proposed, optional)'}
              </Label>
              <Input
                id="waiver-expires"
                data-testid="waiver-expires"
                type="date"
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWaiverMode(null)}>
              Cancel
            </Button>
            <Button
              data-testid="waiver-submit"
              disabled={!rationale.trim() || (waiverMode === 'approve' && !expiresAt)}
              onClick={submitWaiverDialog}
            >
              {waiverMode === 'approve' ? 'Approve waiver' : 'Request waiver'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

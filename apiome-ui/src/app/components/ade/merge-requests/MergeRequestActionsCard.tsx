'use client';

/**
 * The merge request page's aside — where it stands and what to do next (COL-4.3, #4527).
 *
 * - **Summary** — "Ready to merge into main", the number of things to do, or the outcome.
 * - **Blockers** — every reason it cannot merge yet, as apiome-rest's readiness reports them.
 * - **Actions** — **Merge** (enabled only when apiome-rest says it can merge, or when the only thing
 *   in the way is an immutable published line tip and the override is filled in), **Check for
 *   conflicts** (a fresh merge session), **Request review of the current tip** (when the branch moved
 *   on or the review was withdrawn), and **Close**.
 *
 * The override only *forwards* the request: the merge path decides, and refuses anyone but a tenant
 * administrator, recording the reason in the workflow audit log.
 */

import * as React from 'react';
import { GitMerge, RefreshCw, ShieldAlert, XCircle } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Checkbox } from '@/app/components/ui/Checkbox';
import { Label } from '@/app/components/ui/Label';
import { Textarea } from '@/app/components/ui/Textarea';
import { readinessSummary, type MergeRequestDetail } from '@lib/merge-requests';

/** The action buttons, by id. */
export type MergeRequestAction = 'check' | 'merge' | 'close' | 'review';

/** The immutability override the Merge button may carry. */
export interface MergeOverride {
  override_published_immutability: boolean;
  override_reason?: string;
}

export interface MergeRequestActionsCardProps {
  detail: MergeRequestDetail;
  /** The action in flight, if any; every button is disabled meanwhile. */
  busy: MergeRequestAction | null;
  /** The last action's refusal, fit to show. */
  error: string | null;
  /** Run an action; Merge passes the override when it is filled in. */
  onAction: (action: MergeRequestAction, override?: MergeOverride) => void;
}

/** Blockers that a fresh review of the branch tip clears. */
const REVIEW_TIP_BLOCKERS: ReadonlySet<string> = new Set(['review-outdated', 'no-review']);

/**
 * The aside card.
 *
 * @param props - See {@link MergeRequestActionsCardProps}.
 * @returns The card.
 */
export function MergeRequestActionsCard({ detail, busy, error, onAction }: MergeRequestActionsCardProps) {
  const [override, setOverride] = React.useState(false);
  const [reason, setReason] = React.useState('');
  const { merge_request: record, readiness } = detail;
  const open = record.state === 'open';
  const codes = readiness.blockers.map((blocker) => blocker.code);
  const onlyImmutable = codes.length > 0 && codes.every((code) => code === 'target-immutable');
  const overrideReady = override && reason.trim().length > 0;
  const canMerge = open && (readiness.can_merge || (onlyImmutable && overrideReady));
  const offerReview = open && codes.some((code) => REVIEW_TIP_BLOCKERS.has(code));

  return (
    <section className="rvw-card" aria-label="Merge status" data-testid="mr-actions">
      <div className="rvw-card__head">
        <h2 className="rvw-card__title">Status</h2>
      </div>
      <p className="mrq-actions__summary" data-testid="mr-summary">
        {readinessSummary(detail)}
      </p>

      {open && readiness.blockers.length > 0 ? (
        <ul className="mrq-blockers" data-testid="mr-blockers">
          {readiness.blockers.map((blocker) => (
            <li key={blocker.code} className="mrq-blocker" data-testid={`mr-blocker-${blocker.code}`}>
              <ShieldAlert aria-hidden className="mrq-blocker__glyph" />
              <span>{blocker.message}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {open && codes.includes('target-immutable') ? (
        <div className="mrq-override" data-testid="mr-override">
          <label className="vdlg-check vdlg-check--top">
            <Checkbox
              checked={override}
              onCheckedChange={(checked) => {
                setOverride(checked === true);
                if (checked !== true) setReason('');
              }}
              data-testid="mr-override-toggle"
            />
            <span>Override published immutability (tenant administrators only)</span>
          </label>
          {override ? (
            <div className="vdlg-field">
              <Label htmlFor="mr-override-reason">Reason *</Label>
              <Textarea
                id="mr-override-reason"
                rows={3}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why this merge may change a published line (recorded in the audit log)"
                data-testid="mr-override-reason"
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <Alert variant="danger" data-testid="mr-action-error">
          {error}
        </Alert>
      ) : null}

      {open ? (
        <div className="mrq-actions__buttons">
          <Button
            onClick={() =>
              onAction(
                'merge',
                overrideReady ? { override_published_immutability: true, override_reason: reason.trim() } : undefined
              )
            }
            disabled={!canMerge || busy !== null} title={busy !== null ? 'Wait for the current action to finish' : !canMerge ? 'Not ready to merge — resolve the checks above first' : undefined}
            data-testid="mr-merge"
          >
            <GitMerge aria-hidden />
            {busy === 'merge' ? 'Merging…' : `Merge into ${record.target_branch_name}`}
          </Button>
          <Button
            variant="outline"
            onClick={() => onAction('check')}
            disabled={busy !== null} title={busy !== null ? 'Wait for the current action to finish' : undefined}
            data-testid="mr-check"
          >
            <RefreshCw aria-hidden />
            {busy === 'check' ? 'Checking…' : 'Check for conflicts'}
          </Button>
          {offerReview ? (
            <Button
              variant="outline"
              onClick={() => onAction('review')}
              disabled={busy !== null} title={busy !== null ? 'Wait for the current action to finish' : undefined}
              data-testid="mr-review-tip"
            >
              {busy === 'review' ? 'Requesting…' : 'Request review of the current tip'}
            </Button>
          ) : null}
          <Button variant="ghost" onClick={() => onAction('close')} disabled={busy !== null} title={busy !== null ? 'Wait for the current action to finish' : undefined} data-testid="mr-close">
            <XCircle aria-hidden />
            {busy === 'close' ? 'Closing…' : 'Close merge request'}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

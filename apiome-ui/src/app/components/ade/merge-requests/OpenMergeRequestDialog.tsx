'use client';

/**
 * Open merge request — COL-4.3 (#4527).
 *
 * Picks a draft branch and the version line to merge it into (the line it was drafted off by
 * default), a title and description, and the reviewers. apiome-rest requests the COL-2.1 review of
 * the branch tip from those reviewers in the same call; the reviewer list is the workspace's active
 * and pending members, without the person opening it.
 */

import * as React from 'react';
import { GitPullRequestArrow } from 'lucide-react';

import { Alert } from '../../ui/Alert';
import { Button } from '../../ui/Button';
import { Checkbox } from '../../ui/Checkbox';
import { Dialog, DialogContent, DialogFooter } from '../../ui/Dialog';
import { Input } from '../../ui/Input';
import { Label } from '../../ui/Label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../ui/Select';
import { Textarea } from '../../ui/Textarea';
import {
  defaultTargetBranch,
  mergeRequestErrorMessage,
  openMergeRequestFormError,
  openMergeRequestPayload,
  type DraftBranchRecord,
  type MergeRequestDetail,
  type OpenMergeRequestForm,
  type ReviewerCandidate,
} from '@lib/merge-requests';
import { VersionDialogHead } from '../versions/VersionDialogChrome';
import type { VersionBranchRow } from '../version-dialogs/types';
import { callMergeRequestApi } from './mergeRequestFetch';

export interface OpenMergeRequestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  /** The project's draft branches — the possible sources. */
  drafts: ReadonlyArray<DraftBranchRecord>;
  /** The project's branches — the possible targets. */
  branches: ReadonlyArray<VersionBranchRow>;
  /** The draft to preselect. */
  initialSource?: string;
  /** Called with the new merge request. */
  onOpened: (detail: MergeRequestDetail) => void;
}

/** The form for a preselected draft. */
function initialForm(drafts: ReadonlyArray<DraftBranchRecord>, source?: string): OpenMergeRequestForm {
  const sourceBranch = source ?? drafts[0]?.name ?? '';
  return {
    sourceBranch,
    targetBranch: defaultTargetBranch(drafts, sourceBranch),
    title: '',
    description: '',
    reviewers: [],
  };
}

/**
 * The dialog.
 *
 * @param props - See {@link OpenMergeRequestDialogProps}.
 * @returns The dialog.
 */
export function OpenMergeRequestDialog({
  open,
  onOpenChange,
  projectId,
  drafts,
  branches,
  initialSource,
  onOpened,
}: OpenMergeRequestDialogProps) {
  const [form, setForm] = React.useState<OpenMergeRequestForm>(() => initialForm(drafts, initialSource));
  const [candidates, setCandidates] = React.useState<ReviewerCandidate[] | null>(null);
  const [touched, setTouched] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return undefined;
    setForm(initialForm(drafts, initialSource));
    setTouched(false);
    setError(null);
    let cancelled = false;
    (async () => {
      const json = await callMergeRequestApi<{ reviewers: ReviewerCandidate[] }>('/api/merge-requests/reviewers');
      if (!cancelled) setCandidates(json.success && Array.isArray(json.reviewers) ? json.reviewers : []);
    })();
    return () => {
      cancelled = true;
    };
  }, [open, drafts, initialSource]);

  const formError = openMergeRequestFormError(form);
  const targets = branches.filter((branch) => branch.name !== form.sourceBranch);

  const toggleReviewer = (userId: string, checked: boolean) => {
    setForm((previous) => ({
      ...previous,
      reviewers: checked
        ? [...previous.reviewers, userId]
        : previous.reviewers.filter((reviewer) => reviewer !== userId),
    }));
  };

  const submit = async () => {
    setTouched(true);
    if (formError) return;
    setSaving(true);
    setError(null);
    const json = await callMergeRequestApi<{ mergeRequest: MergeRequestDetail }>(
      `/api/projects/${encodeURIComponent(projectId)}/merge-requests`,
      openMergeRequestPayload(form)
    );
    setSaving(false);
    if (!json.success || !json.mergeRequest) {
      setError(mergeRequestErrorMessage(json.code, json.error || 'Could not open the merge request.'));
      return;
    }
    onOpened(json.mergeRequest);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : undefined)}>
      <DialogContent className="vdlg-dialog vdlg-dialog--lg" aria-describedby={undefined} data-testid="open-mr-dialog">
        <VersionDialogHead
          icon={<GitPullRequestArrow aria-hidden />}
          tone="violet"
          title="Open merge request"
          description="Ask reviewers to review a draft branch. It merges into the version line once they approve."
        />
        <div className="vdlg-form">
          <div className="mrq-form__row">
            <div className="vdlg-field mrq-form__field">
              <Label>Draft branch</Label>
              <Select
                value={form.sourceBranch || undefined}
                onValueChange={(value) =>
                  setForm({ ...form, sourceBranch: value, targetBranch: defaultTargetBranch(drafts, value) })
                }
              >
                <SelectTrigger data-testid="open-mr-source">
                  <SelectValue placeholder="Choose a draft branch" />
                </SelectTrigger>
                <SelectContent>
                  {drafts.map((draft) => (
                    <SelectItem key={draft.id} value={draft.name}>
                      {draft.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="vdlg-field mrq-form__field">
              <Label>Merge into</Label>
              <Select
                value={form.targetBranch || undefined}
                onValueChange={(value) => setForm({ ...form, targetBranch: value })}
              >
                <SelectTrigger data-testid="open-mr-target">
                  <SelectValue placeholder="Choose a version line" />
                </SelectTrigger>
                <SelectContent>
                  {targets.map((branch) => (
                    <SelectItem key={branch.id} value={branch.name}>
                      {branch.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="vdlg-field">
            <Label htmlFor="open-mr-title">Title</Label>
            <Input
              id="open-mr-title"
              value={form.title}
              onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="Add tags to Pet"
              data-testid="open-mr-title"
            />
          </div>
          <div className="vdlg-field">
            <Label htmlFor="open-mr-description">Description (optional)</Label>
            <Textarea
              id="open-mr-description"
              rows={3}
              value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
              placeholder="What changes, and why"
              data-testid="open-mr-description"
            />
          </div>
          <fieldset className="mrq-reviewers" data-testid="open-mr-reviewers">
            <legend className="mrq-reviewers__legend">Reviewers</legend>
            {candidates === null ? (
              <p className="mrq-reviewers__empty">Loading members…</p>
            ) : candidates.length === 0 ? (
              <p className="mrq-reviewers__empty">Nobody else in this workspace can review yet.</p>
            ) : (
              candidates.map((candidate) => (
                <label key={candidate.user_id} className="vdlg-check" data-testid="open-mr-reviewer">
                  <Checkbox
                    checked={form.reviewers.includes(candidate.user_id)}
                    onCheckedChange={(checked) => toggleReviewer(candidate.user_id, checked === true)}
                  />
                  <span>
                    {candidate.name || candidate.email || candidate.user_id}
                    {candidate.name && candidate.email ? (
                      <span className="mrq-reviewers__email"> · {candidate.email}</span>
                    ) : null}
                  </span>
                </label>
              ))
            )}
          </fieldset>
          {touched && formError ? (
            <Alert variant="warn" data-testid="open-mr-form-error">
              {formError}
            </Alert>
          ) : null}
          {error ? (
            <Alert variant="danger" data-testid="open-mr-error">
              {error}
            </Alert>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving} data-testid="open-mr-submit">
            {saving ? 'Opening…' : 'Open merge request'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

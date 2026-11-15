'use client';

/**
 * New draft branch — COL-4.3 (#4527).
 *
 * Names a branch and picks the **version line** (an existing branch) to draft it off. apiome-rest
 * copies the line's tip into the branch's own draft revision, so editing the branch never touches
 * the line; the optional version label names that revision (blank takes the next patch version).
 */

import * as React from 'react';
import { GitBranchPlus } from 'lucide-react';

import { Alert } from '../../ui/Alert';
import { Button } from '../../ui/Button';
import { Dialog, DialogContent, DialogFooter } from '../../ui/Dialog';
import { Input } from '../../ui/Input';
import { Label } from '../../ui/Label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../../ui/Select';
import {
  draftBranchFormError,
  draftBranchPayload,
  mergeRequestErrorMessage,
  type DraftBranchForm,
  type DraftBranchRecord,
} from '@lib/merge-requests';
import { VersionDialogHead } from '../versions/VersionDialogChrome';
import type { VersionBranchRow } from '../version-dialogs/types';
import { callMergeRequestApi } from './mergeRequestFetch';

export interface NewDraftBranchDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  /** The project's branches — the lines a draft can start from, and the names already taken. */
  branches: ReadonlyArray<VersionBranchRow>;
  /** Called with the new branch once it exists. */
  onCreated: (branch: DraftBranchRecord) => void;
}

/** The form before anything is typed: the default branch is the usual line. */
function initialForm(branches: ReadonlyArray<VersionBranchRow>): DraftBranchForm {
  const line = branches.find((branch) => branch.is_default) ?? branches[0];
  return { name: '', baseBranch: line?.name ?? '', versionLabel: '' };
}

/**
 * The dialog.
 *
 * @param props - See {@link NewDraftBranchDialogProps}.
 * @returns The dialog.
 */
export function NewDraftBranchDialog({ open, onOpenChange, projectId, branches, onCreated }: NewDraftBranchDialogProps) {
  const [form, setForm] = React.useState<DraftBranchForm>(() => initialForm(branches));
  const [touched, setTouched] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setForm(initialForm(branches));
      setTouched(false);
      setError(null);
    }
  }, [open, branches]);

  const formError = draftBranchFormError(
    form,
    branches.map((branch) => branch.name)
  );

  const submit = async () => {
    setTouched(true);
    if (formError) return;
    setSaving(true);
    setError(null);
    const json = await callMergeRequestApi<{ branch: DraftBranchRecord }>(
      `/api/projects/${encodeURIComponent(projectId)}/draft-branches`,
      draftBranchPayload(form)
    );
    setSaving(false);
    if (!json.success || !json.branch) {
      setError(mergeRequestErrorMessage(json.code, json.error || 'Could not create the branch.'));
      return;
    }
    onCreated(json.branch);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : undefined)}>
      <DialogContent className="vdlg-dialog" aria-describedby={undefined} data-testid="draft-branch-dialog">
        <VersionDialogHead
          icon={<GitBranchPlus aria-hidden />}
          tone="accent"
          title="New draft branch"
          description="Draft changes on a branch of their own. The version line stays as it is until you merge."
        />
        <div className="vdlg-form">
          <div className="vdlg-field">
            <Label htmlFor="draft-branch-name">Branch name</Label>
            <Input
              id="draft-branch-name"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="feature/pet-tags"
              autoFocus
              data-testid="draft-branch-name"
            />
          </div>
          <div className="vdlg-field">
            <Label>Version line</Label>
            <Select value={form.baseBranch || undefined} onValueChange={(value) => setForm({ ...form, baseBranch: value })}>
              <SelectTrigger data-testid="draft-branch-base">
                <SelectValue placeholder="Choose a branch" />
              </SelectTrigger>
              <SelectContent>
                {branches.map((branch) => (
                  <SelectItem key={branch.id} value={branch.name}>
                    {branch.name}
                    {branch.tip_version_string ? ` · v${branch.tip_version_string.replace(/^v/, '')}` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="vdlg-field">
            <Label htmlFor="draft-branch-label">Version label (optional)</Label>
            <Input
              id="draft-branch-label"
              value={form.versionLabel}
              onChange={(event) => setForm({ ...form, versionLabel: event.target.value })}
              placeholder="Next patch version"
              data-testid="draft-branch-label"
            />
          </div>
          {touched && formError ? (
            <Alert variant="warn" data-testid="draft-branch-form-error">
              {formError}
            </Alert>
          ) : null}
          {error ? (
            <Alert variant="danger" data-testid="draft-branch-error">
              {error}
            </Alert>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={saving} data-testid="draft-branch-create">
            {saving ? 'Creating…' : 'Create branch'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

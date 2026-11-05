'use client';

/**
 * Per-branch refresh rules panel (RAR-6.4, #3541).
 *
 * A repository often tracks several branches — `main`, release branches, a sandbox — and each
 * stands for a different line of the API. This panel sets, per branch or per glob, whether the
 * branch refreshes, how often, and the version line its refreshes land in.
 *
 * Two things drive the design:
 *
 *  * **The effect is shown, not just the rules.** Globs and "most specific wins" are easy to get
 *    wrong, so every tracked branch is listed with the sentence that says how it refreshes and
 *    which rule (if any) decided it. That list is the server's answer, re-read after each save.
 *  * **The rules are saved as one set.** Rows are edited locally and **Save rules** writes them
 *    all, so the server never holds a half-edited mix; the button is enabled only when something
 *    changed.
 *
 * Reads and writes go through `/api/repositories/{id}/branch-refresh-rules`.
 */

import { useCallback, useEffect, useState } from 'react';
import { GitBranch, Plus, Trash2 } from 'lucide-react';
import { toast } from '../../../ui/toast';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardContent } from '@/app/components/ui/Card';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { Switch } from '@/app/components/ui/Switch';
import {
  INHERIT_INTERVAL,
  type BranchRefreshData,
  type BranchRuleDraft,
  cadenceChoices,
  describeBranchRefresh,
  draftsChanged,
  draftsFromRules,
  draftsToRequest,
  formatCadence,
  newDraft,
  parseBranchRefreshResponse,
  validateDrafts,
} from '@/app/components/ade/dashboard/repositories/repositoryBranchRefresh';

/**
 * Render the branch refresh rules card for one repository.
 *
 * @param props.repositoryId The repository whose rules this panel edits.
 * @returns The card (loading, error, or the rules and tracked branches).
 */
export function RepositoryBranchRefreshRules({ repositoryId }: { repositoryId: string }) {
  const [data, setData] = useState<BranchRefreshData | null>(null);
  const [drafts, setDrafts] = useState<BranchRuleDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const api = `/api/repositories/${encodeURIComponent(repositoryId)}/branch-refresh-rules`;

  /** Show a projection from the server and reset the drafts to it. */
  const accept = (body: unknown) => {
    const parsed = parseBranchRefreshResponse(body);
    setData(parsed);
    setDrafts(draftsFromRules(parsed.rules));
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(api, { credentials: 'include' });
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) throw new Error(typeof body.error === 'string' ? body.error : res.statusText);
      accept(body);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the branch refresh rules.');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (!repositoryId) return;
    void load();
  }, [repositoryId, load]);

  const update = (key: string, patch: Partial<BranchRuleDraft>) =>
    setDrafts((current) => current.map((d) => (d.key === key ? { ...d, ...patch } : d)));

  const save = async () => {
    const problem = validateDrafts(drafts);
    if (problem) {
      toast.error(problem);
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(api, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draftsToRequest(drafts)),
      });
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) throw new Error(typeof body.error === 'string' ? body.error : res.statusText);
      accept(body);
      toast.success('Branch refresh rules saved.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the branch refresh rules.');
    } finally {
      setSaving(false);
    }
  };

  if (loading && !data) {
    return (
      <Card data-testid="branch-refresh-loading">
        <CardContent className="flex flex-col gap-2">
          <h3 className="repo-det-card__title">Branch refresh rules</h3>
          <p className="repo-det-note">Loading branch refresh rules…</p>
        </CardContent>
      </Card>
    );
  }

  if (error && !data) {
    return (
      <ErrorState
        data-testid="branch-refresh-error"
        title="Branch refresh rules"
        description={error}
        onRetry={() => void load()}
      />
    );
  }

  if (!data) return null;

  const dirty = draftsChanged(drafts, data.rules);

  return (
    <Card data-testid="branch-refresh">
      <CardContent className="flex flex-col gap-4" role="group" aria-label="Branch refresh rules">
        <div className="flex flex-col gap-1">
          <h3 className="repo-det-card__title">Branch refresh rules</h3>
          <p className="repo-det-note">
            Set, per branch, whether it refreshes, how often, and the version line its refreshes land
            in — the refreshed version is named <span className="mono">line-UTC timestamp</span>. Name a
            branch exactly (<span className="mono">main</span>) or with a pattern (
            <span className="mono">release/*</span>); the most specific rule wins, and a branch no rule
            matches follows the repository: every {formatCadence(data.repositoryIntervalSeconds)}.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <h4 className="repo-det-caps flex items-center gap-2">
            <GitBranch className="size-3.5 shrink-0" aria-hidden />
            Tracked branches
          </h4>
          {data.branches.length === 0 ? (
            <p className="repo-det-note" data-testid="branch-refresh-no-branches">
              No branch has an imported file yet.
            </p>
          ) : (
            <ul className="flex flex-col gap-2" data-testid="branch-refresh-branches">
              {data.branches.map((b) => (
                <li key={b.branch} className="repo-det-row" data-testid={`branch-refresh-branch-${b.branch}`}>
                  <span className="mono min-w-0 truncate text-xs">{b.branch}</span>
                  <span className="repo-det-note truncate">
                    {describeBranchRefresh(b, data.autoRefreshEnabled)}
                  </span>
                  <span className="repo-det-row__end">
                    <Badge variant={b.enabled && data.autoRefreshEnabled ? 'ok' : 'outline'}>
                      {b.enabled && data.autoRefreshEnabled ? 'Refreshes' : 'Off'}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <fieldset className="flex flex-col gap-3" disabled={saving}>
          <legend className="repo-det-caps">Rules</legend>
          {drafts.length === 0 ? (
            <p className="repo-det-note" data-testid="branch-refresh-no-rules">
              No rules — every branch follows the repository settings.
            </p>
          ) : (
            drafts.map((draft, index) => {
              const id = `branch-rule-${index}`;
              const choices = cadenceChoices(
                data.minIntervalSeconds,
                draft.interval === INHERIT_INTERVAL ? null : Number(draft.interval)
              );
              return (
                <div key={draft.key} className="repo-set-branch-rule" data-testid={`branch-refresh-rule-${index}`}>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`${id}-pattern`}>Branch</Label>
                    <Input
                      id={`${id}-pattern`}
                      value={draft.branchPattern}
                      placeholder="release/*"
                      className="mono"
                      onChange={(e) => update(draft.key, { branchPattern: e.target.value })}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`${id}-enabled`}>Refresh</Label>
                    <Switch
                      id={`${id}-enabled`}
                      checked={draft.refreshEnabled}
                      onCheckedChange={(next) => update(draft.key, { refreshEnabled: next })}
                      aria-label={`Refresh branches matching ${draft.branchPattern || 'this rule'}`}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`${id}-interval`}>Every</Label>
                    <Select
                      value={draft.interval}
                      onValueChange={(value) => update(draft.key, { interval: value })}
                    >
                      <SelectTrigger id={`${id}-interval`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={INHERIT_INTERVAL}>
                          Repository ({formatCadence(data.repositoryIntervalSeconds)})
                        </SelectItem>
                        {choices.map((seconds) => (
                          <SelectItem key={seconds} value={String(seconds)}>
                            {formatCadence(seconds)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={`${id}-line`}>Version line</Label>
                    <Input
                      id={`${id}-line`}
                      value={draft.targetVersionLine}
                      placeholder="2.x"
                      className="mono"
                      onChange={(e) => update(draft.key, { targetVersionLine: e.target.value })}
                    />
                  </div>
                  <div className="repo-set-branch-rule__remove">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setDrafts((current) => current.filter((d) => d.key !== draft.key))}
                      aria-label={`Remove the rule for ${draft.branchPattern || 'this branch'}`}
                    >
                      <Trash2 aria-hidden />
                      Remove
                    </Button>
                  </div>
                </div>
              );
            })
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={() => setDrafts((current) => [...current, newDraft()])}>
              <Plus aria-hidden />
              Add rule
            </Button>
            <Button title={!dirty ? 'Change a rule first' : undefined} type="button" disabled={!dirty} onClick={() => void save()} data-testid="branch-refresh-save">
              Save rules
            </Button>
          </div>
        </fieldset>
      </CardContent>
    </Card>
  );
}

export default RepositoryBranchRefreshRules;

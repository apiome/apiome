'use client';

/**
 * The workspace refresh defaults screen (RAR-6.5, #3542).
 *
 * A workspace administrator sets the cadence, conflict policy and auto-refresh switch every new
 * repository starts from. Each repository follows a default per setting until that one setting is
 * changed on the repository, so the screen says how many repositories follow each default, and a
 * save can re-apply the defaults to exactly those settings — never to one a repository overrides.
 *
 * Everyone who can see repositories can read the defaults; only an administrator can change them,
 * and the form says so rather than failing on save.
 */

import * as React from 'react';
import { useAuthSession } from '@lib/auth/session-client';
import { toast } from '../../../../components/ui/toast';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card, CardContent } from '@/app/components/ui/Card';
import { Checkbox } from '@/app/components/ui/Checkbox';
import { GatedState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Label } from '@/app/components/ui/Label';
import { LoadingState } from '@/app/components/ui/LoadingState';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { Switch } from '@/app/components/ui/Switch';
import { RepositoriesSubNav } from '@/app/components/ade/repositories';
import { ConflictPolicyOption } from '@/app/components/ade/dashboard/repositories/RepositoryConflictPolicy';
import {
  asConflictPolicy,
  CONFLICT_POLICIES,
} from '@/app/components/ade/dashboard/repositories/repositoryConflictPolicy';
import {
  cadenceChoices,
  formatCadence,
} from '@/app/components/ade/dashboard/repositories/repositoryBranchRefresh';
import {
  type RefreshDefaultsData,
  type RefreshDefaultsDraft,
  appliedSentence,
  defaultsChanged,
  draftFromDefaults,
  inheritanceSentence,
  parseRefreshDefaults,
} from '@/app/components/ade/repositories/refreshDefaultsModel';

/** The API route this screen reads and writes. */
const API = '/api/repositories/refresh-defaults';

/**
 * The refresh defaults screen.
 *
 * @returns The page.
 */
export function RefreshDefaultsClient() {
  const { data: session } = useAuthSession();
  const currentTenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;

  const [data, setData] = React.useState<RefreshDefaultsData | null>(null);
  const [draft, setDraft] = React.useState<RefreshDefaultsDraft | null>(null);
  const [applyToInheriting, setApplyToInheriting] = React.useState(true);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  /** Show what the server returned, and reset the form to it. */
  const accept = (body: unknown) => {
    const parsed = parseRefreshDefaults(body);
    setData(parsed);
    setDraft(draftFromDefaults(parsed));
    return parsed;
  };

  const load = React.useCallback(async () => {
    if (!currentTenantId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(API, { credentials: 'include' });
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) throw new Error(typeof body.error === 'string' ? body.error : res.statusText);
      accept(body);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the refresh defaults.');
    } finally {
      setLoading(false);
    }
  }, [currentTenantId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const res = await fetch(API, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...draft, applyToInheriting }),
      });
      const body = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) throw new Error(typeof body.error === 'string' ? body.error : res.statusText);
      const parsed = accept(body);
      toast.success(parsed.applied ? appliedSentence(parsed.applied) : 'Defaults saved. New repositories start from them.');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the refresh defaults.');
    } finally {
      setSaving(false);
    }
  };

  const editable = Boolean(data?.canEdit) && !saving;

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: '/ade/dashboard' },
          { label: 'Bring in' },
          { label: 'Repositories', href: '/ade/dashboard/repositories' },
          { label: 'Refresh defaults' },
        ]}
        title="Refresh defaults"
        description="The cadence, conflict policy and auto-refresh switch every new repository starts from. A repository follows each default until that setting is changed on it."
        tabs={<RepositoriesSubNav active="defaults" />}
      />
      <PageBody>
        {!currentTenantId ? (
          <GatedState description="Choose a workspace to see its refresh defaults." />
        ) : error && !data ? (
          <ErrorState
            title="Refresh defaults"
            description={error}
            onRetry={() => void load()}
            data-testid="refresh-defaults-error"
          />
        ) : loading && !data ? (
          <LoadingState message="Loading refresh defaults…" />
        ) : data && draft ? (
          <Card data-testid="refresh-defaults">
            <CardContent className="flex flex-col gap-5">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="repo-det-card__title">Workspace defaults</h3>
                <Badge variant={data.configured ? 'ok' : 'outline'}>
                  {data.configured ? 'Set for this workspace' : 'Built-in values'}
                </Badge>
              </div>
              {!data.canEdit ? (
                <p className="repo-det-note" data-testid="refresh-defaults-read-only">
                  Only workspace administrators can change the defaults.
                </p>
              ) : null}

              <div className="repo-set-defaults__row">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="refresh-defaults-interval">Cadence</Label>
                  <Select
                    value={String(draft.refreshIntervalSeconds)}
                    disabled={!editable}
                    onValueChange={(value) => setDraft({ ...draft, refreshIntervalSeconds: Number(value) })}
                  >
                    <SelectTrigger id="refresh-defaults-interval" className="max-w-[14rem]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {cadenceChoices(data.minIntervalSeconds, draft.refreshIntervalSeconds).map((seconds) => (
                        <SelectItem key={seconds} value={String(seconds)}>
                          Every {formatCadence(seconds)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <p className="repo-det-note" data-testid="refresh-defaults-follow-interval">
                  {inheritanceSentence(data, 'refresh_interval')}
                </p>
              </div>

              <fieldset className="flex flex-col gap-2" disabled={!editable}>
                <legend className="repo-det-caps">Refresh conflicts</legend>
                {CONFLICT_POLICIES.map((policy) => (
                  <ConflictPolicyOption
                    key={policy}
                    name="refresh-defaults-conflict-policy"
                    policy={policy}
                    selected={draft.conflictPolicy === policy}
                    disabled={!editable}
                    onSelect={(next) => setDraft({ ...draft, conflictPolicy: asConflictPolicy(next) })}
                  />
                ))}
                <p className="repo-det-note" data-testid="refresh-defaults-follow-policy">
                  {inheritanceSentence(data, 'conflict_policy')}
                </p>
              </fieldset>

              <div className="repo-set-switch">
                <div className="repo-set-switch__text">
                  <Label htmlFor="refresh-defaults-auto-refresh">Auto-refresh</Label>
                  <p className="repo-det-note" data-testid="refresh-defaults-follow-auto">
                    {inheritanceSentence(data, 'auto_refresh')}
                  </p>
                </div>
                <Switch
                  id="refresh-defaults-auto-refresh"
                  checked={draft.autoRefreshEnabled}
                  disabled={!editable}
                  onCheckedChange={(next) => setDraft({ ...draft, autoRefreshEnabled: next })}
                  aria-label="Auto-refresh new repositories"
                />
              </div>

              {data.canEdit ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-start gap-2">
                    <Checkbox
                      id="refresh-defaults-apply"
                      checked={applyToInheriting}
                      disabled={saving}
                      onCheckedChange={(next) => setApplyToInheriting(next === true)}
                    />
                    <Label htmlFor="refresh-defaults-apply" className="font-normal">
                      Also apply to the repositories that follow these defaults. A setting changed on a
                      repository is never touched.
                    </Label>
                  </div>
                  <div>
                    <Button
                      type="button"
                      disabled={saving || (!defaultsChanged(draft, data) && !applyToInheriting)}
                      onClick={() => void save()}
                      data-testid="refresh-defaults-save"
                    >
                      Save defaults
                    </Button>
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
      </PageBody>
    </Page>
  );
}

export default RefreshDefaultsClient;

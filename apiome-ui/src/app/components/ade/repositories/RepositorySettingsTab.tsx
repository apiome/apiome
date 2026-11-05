'use client';

/**
 * The repository's own settings (HIVE-7.5, #5322).
 *
 * Authority: `docs/mockups/sources/repository-detail.html` §Settings — the *Source* card, the
 * *Scan cadence* switch over its disabled fieldset, *Refresh conflicts* (which stays
 * {@link RepositoryConflictPolicy}, its own RAR-4.5 panel), *Pull requests back* (REPO-5.8's
 * {@link RepositoryPrBackSettings}, passed in the same way), *Default importer mappings*, and the
 * danger zone.
 *
 * ### The one thing this fixes rather than restyles
 *
 * Three of the five cards here draw controls that do nothing yet — a subpath glob, a schedule,
 * a webhook, an "Add mapping" button. The screen this replaces marked them by dimming: a
 * `fieldset disabled` at `opacity-70`, a `disabled` input, a `disabled` button. Dimming says
 * "not now"; it does not say *why*, and a reader who cannot see the difference between a
 * disabled control and an enabled one on their display gets no signal at all.
 *
 * So every stub here carries its sentence in text, from the shared vocabulary in
 * `repositoryDetailModel` — {@link SUBPATH_GLOB_STUB_NOTE} and the four beside it — and the
 * dimming is the second channel rather than the only one. That is the ticket's "stubbed
 * controls remain visually honest" criterion, and DESIGN.md §6 besides.
 */

import * as React from 'react';
import { Plus } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { Card, CardContent } from '@/app/components/ui/Card';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Switch } from '@/app/components/ui/Switch';
import { Badge } from '@/app/components/ui/Badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import {
  CADENCE_CHOICES,
  cadenceChoices,
  formatCadence,
} from '@/app/components/ade/dashboard/repositories/repositoryBranchRefresh';
import { POLICY_COPY, asConflictPolicy } from '@/app/components/ade/dashboard/repositories/repositoryConflictPolicy';

import { ProviderGlyph } from './ProviderBadge';
import {
  AUTO_REFRESH_DESCRIPTION,
  IMPORTER_MAPPINGS_EMPTY,
  IMPORTER_MAPPINGS_STUB_NOTE,
  REMOVE_REPOSITORY_DESCRIPTION,
  SUBPATH_GLOB_STUB_NOTE,
  WEBHOOK_STUB_NOTE,
  repositorySourceLine,
} from './repositoryDetailModel';
import type { DashboardRepository } from './repositoriesModel';
import {
  REFRESH_SETTINGS,
  REFRESH_SETTING_LABELS,
  type RefreshSetting,
  settingValueText,
} from './refreshDefaultsModel';

/** Where a repository's "Workspace defaults" rows link to (RAR-6.5). */
export const REFRESH_DEFAULTS_HREF = '/ade/dashboard/repositories/refresh-defaults';

export interface RepositorySettingsTabProps {
  /** The repository being configured. */
  repository: DashboardRepository;
  /** Its page on the provider's website, when there is one. */
  webUrl: string | null;
  /** True while the auto-refresh write is in flight. */
  savingAutoRefresh: boolean;
  /** Flip this repository's auto-refresh opt-out. */
  onToggleAutoRefresh: (next: boolean) => void;
  /** True while a cadence or workspace-default write is in flight (RAR-6.5). */
  savingRefreshSettings?: boolean;
  /** Set this repository's cadence, overriding the workspace default (RAR-6.5). */
  onChangeInterval?: (seconds: number) => void;
  /** Make one refresh setting follow the workspace default again (RAR-6.5). */
  onUseWorkspaceDefault?: (setting: RefreshSetting) => void;
  /** Open the remove confirm. */
  onRemove: () => void;
  /** True while the delete is in flight. */
  removing: boolean;
  /** The RAR-4.5 conflict-policy panel, passed in so this tab owns no data of its own. */
  conflictPolicy: React.ReactNode;
  /** The RAR-6.4 per-branch refresh rules panel, passed in for the same reason. */
  branchRefresh?: React.ReactNode;
  /** The REPO-5.8 PR-back settings card, passed in for the same reason. */
  prBack?: React.ReactNode;
}

/** The importer-mappings table's four columns. */
const MAPPING_COLUMNS = ['Path glob', 'Detected kind', 'Default project', 'Actions'] as const;

/**
 * Render the Settings tab. See {@link RepositorySettingsTabProps}.
 *
 * @returns The five cards, in the mockup's order.
 */
export function RepositorySettingsTab({
  repository,
  webUrl,
  savingAutoRefresh,
  onToggleAutoRefresh,
  savingRefreshSettings = false,
  onChangeInterval,
  onUseWorkspaceDefault,
  onRemove,
  removing,
  conflictPolicy,
  branchRefresh,
  prBack,
}: RepositorySettingsTabProps) {
  const autoRefreshOn = repository.auto_refresh_enabled ?? true;
  const interval = repository.refresh_interval_seconds ?? null;
  const inherits: Record<RefreshSetting, boolean> = {
    refresh_interval: repository.inherits_refresh_interval !== false,
    conflict_policy: repository.inherits_conflict_policy !== false,
    auto_refresh: repository.inherits_auto_refresh !== false,
  };
  const settingValue: Record<RefreshSetting, number | string | boolean | null | undefined> = {
    refresh_interval: interval,
    conflict_policy: repository.refresh_conflict_policy,
    auto_refresh: autoRefreshOn,
  };
  const policyLabel = (policy: string) => POLICY_COPY[asConflictPolicy(policy)].label;

  return (
    <div className="flex max-w-[57.5rem] flex-col gap-6" data-testid="repository-settings-tab">
      <Card data-testid="repository-settings-source">
        <CardContent className="flex flex-col gap-3">
          <h3 className="repo-det-card__title">Source</h3>
          <dl className="repo-set-kv">
            <dt>Provider</dt>
            <dd className="flex items-center gap-2" data-provider={repository.provider}>
              <ProviderGlyph provider={repository.provider} />
              {repositorySourceLine(repository.provider, repository.source)}
            </dd>

            <dt>Clone URL</dt>
            <dd className="flex flex-wrap items-center gap-3">
              <span className="mono text-xs">{repository.clone_url ?? '—'}</span>
              {webUrl ? (
                <a
                  href={webUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="repo-det-link"
                >
                  Open in browser →
                </a>
              ) : null}
            </dd>

            <dt>
              <Label htmlFor="repository-default-branch">Default branch</Label>
            </dt>
            <dd>
              <Input
                id="repository-default-branch"
                readOnly
                aria-readonly="true"
                value={repository.default_branch}
                className="mono max-w-[12rem]"
              />
            </dd>

            <dt>
              <Label htmlFor="repository-subpath-glob">Subpath glob (optional)</Label>
            </dt>
            <dd className="flex flex-col gap-1">
              <Input
                id="repository-subpath-glob"
                disabled
                placeholder="e.g. specs/**"
                className="mono max-w-[18rem]"
              />
              <p className="repo-det-note" data-testid="repository-subpath-stub">
                {SUBPATH_GLOB_STUB_NOTE}
              </p>
            </dd>
          </dl>
        </CardContent>
      </Card>

      <Card data-testid="repository-settings-cadence">
        <CardContent className="flex flex-col gap-4">
          <h3 className="repo-det-card__title">Scan cadence</h3>
          <div className="repo-set-switch">
            <div className="repo-set-switch__text">
              <span className="flex items-center gap-2 text-sm font-medium text-fg">
                <Label htmlFor="repository-auto-refresh">Auto-refresh</Label>
                <Badge variant={autoRefreshOn ? 'ok' : 'outline'}>
                  {autoRefreshOn ? 'Enabled' : 'Disabled'}
                </Badge>
              </span>
              <p className="repo-det-note">{AUTO_REFRESH_DESCRIPTION}</p>
            </div>
            <Switch
              id="repository-auto-refresh"
              checked={autoRefreshOn}
              disabled={savingAutoRefresh}
              onCheckedChange={onToggleAutoRefresh}
              aria-label="Toggle auto-refresh for this repository"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="repository-interval">Cadence</Label>
            <Select
              value={interval === null ? undefined : String(interval)}
              disabled={savingRefreshSettings || !onChangeInterval}
              onValueChange={(value) => onChangeInterval?.(Number(value))}
            >
              <SelectTrigger id="repository-interval" className="max-w-[14rem]" data-testid="repository-interval">
                <SelectValue placeholder="Not reported" />
              </SelectTrigger>
              <SelectContent>
                {cadenceChoices(CADENCE_CHOICES[0], interval).map((seconds) => (
                  <SelectItem key={seconds} value={String(seconds)}>
                    Every {formatCadence(seconds)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <fieldset disabled className="repo-set-stub" data-testid="repository-cadence-stub">
            <div className="repo-set-stub__grid">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="repository-webhook">Webhook</Label>
                <Input id="repository-webhook" readOnly value={WEBHOOK_STUB_NOTE} />
              </div>
            </div>
          </fieldset>
          <p className="repo-det-note">
            Webhook secrets are not wired here yet, and the field says so above.
          </p>

          <div className="flex flex-col gap-2" data-testid="repository-refresh-inheritance">
            <h4 className="repo-det-caps">Workspace defaults</h4>
            <p className="repo-det-note">
              Each setting follows the workspace{' '}
              <a href={REFRESH_DEFAULTS_HREF} className="repo-det-link">
                refresh defaults
              </a>{' '}
              until it is changed here.
            </p>
            <div className="repo-set-inherit">
              {REFRESH_SETTINGS.map((setting) => (
                <React.Fragment key={setting}>
                  <span className="text-sm font-medium text-fg">{REFRESH_SETTING_LABELS[setting]}</span>
                  <span className="repo-det-note" data-testid={`repository-refresh-value-${setting}`}>
                    {settingValueText(setting, settingValue[setting], policyLabel)}
                  </span>
                  <Badge
                    variant={inherits[setting] ? 'outline' : 'warn'}
                    data-testid={`repository-refresh-source-${setting}`}
                  >
                    {inherits[setting] ? 'Workspace default' : 'Custom'}
                  </Badge>
                  {inherits[setting] ? (
                    <span />
                  ) : (
                    <Button title={savingRefreshSettings ? 'Wait for the save to finish' : !onUseWorkspaceDefault ? 'You can’t change refresh settings here' : undefined}
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={savingRefreshSettings || !onUseWorkspaceDefault}
                      onClick={() => onUseWorkspaceDefault?.(setting)}
                      data-testid={`repository-use-default-${setting}`}
                    >
                      Use workspace default
                    </Button>
                  )}
                </React.Fragment>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {branchRefresh}

      {conflictPolicy}

      {prBack}

      <Card data-testid="repository-settings-mappings">
        <CardContent className="flex flex-col gap-3">
          <h3 className="repo-det-card__title">Default importer mappings</h3>
          <p className="repo-det-note">{IMPORTER_MAPPINGS_STUB_NOTE}</p>
          <div className="repo-det-table-scroll">
            <table className="repo-det-table table-density table-dense">
              <thead>
                <tr>
                  {MAPPING_COLUMNS.map((column) => (
                    <th key={column} scope="col">
                      {column === 'Actions' ? <span className="sr-only">Actions</span> : column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td colSpan={MAPPING_COLUMNS.length} className="repo-det-table__state">
                    {IMPORTER_MAPPINGS_EMPTY}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <Button type="button" variant="outline" size="sm" disabled>
              <Plus aria-hidden />
              Add mapping
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="repo-set-danger" data-testid="repository-danger-zone">
        <CardContent className="flex flex-col gap-3">
          <h3 className="repo-set-danger__title">Danger zone</h3>
          <div className="repo-set-danger__row">
            <p className="repo-set-danger__copy">{REMOVE_REPOSITORY_DESCRIPTION}</p>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={removing}
              onClick={onRemove}
              data-testid="repository-remove"
            >
              Remove repository
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default RepositorySettingsTab;

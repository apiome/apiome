'use client';

/**
 * The manage drawer's **Ownership** section — CDG-2.5 (#5964).
 *
 * Two workspace settings:
 *
 * - **Catch-all team** — the team that also receives findings on anything with no confirmed owner
 *   (they are still listed in the Unowned findings report). "None" keeps the report only.
 * - **Require an owner to publish** — publishing a version of a project with no confirmed owner team
 *   is refused with reason `no-owner`; the publish dialog shows the gate either way.
 *
 * Both are saved together with **Save changes**; reading needs `teams:view` and saving `teams:edit`
 * (REST enforces both). The section reads the session's current tenant, like the MCP sections.
 */

import * as React from 'react';
import { Lock } from 'lucide-react';
import { Alert, Button, Label, LoadingState, Switch } from '@/app/components/ui';
import type { OwnershipPolicy, Team } from '@lib/owners';
import { fetchOwnershipPolicy, fetchTeams, saveOwnershipPolicy } from '@/app/components/ade/owners/ownersApi';

/** Props for {@link TenantOwnershipPolicySection}. */
export interface TenantOwnershipPolicySectionProps {
  /** Whether the reader administers the tenant; others see the policy read-only. */
  isAdmin: boolean;
  /** Reports unsaved changes, so the drawer can mark the tab. */
  onDirtyChange?: (dirty: boolean) => void;
}

/**
 * The Ownership section.
 *
 * @param props - See {@link TenantOwnershipPolicySectionProps}.
 * @returns The form.
 */
export default function TenantOwnershipPolicySection({ isAdmin, onDirtyChange }: TenantOwnershipPolicySectionProps) {
  const [policy, setPolicy] = React.useState<OwnershipPolicy | null>(null);
  const [teams, setTeams] = React.useState<Team[]>([]);
  const [catchAll, setCatchAll] = React.useState('');
  const [requireOwner, setRequireOwner] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  const reset = React.useCallback((next: OwnershipPolicy) => {
    setPolicy(next);
    setCatchAll(next.unowned_findings_team && !next.unowned_findings_team.deleted ? next.unowned_findings_team.slug : '');
    setRequireOwner(next.require_owner_to_publish);
  }, []);

  React.useEffect(() => {
    let live = true;
    Promise.all([fetchOwnershipPolicy(), fetchTeams()])
      .then(([nextPolicy, nextTeams]) => {
        if (!live) return;
        setTeams(nextTeams);
        reset(nextPolicy);
      })
      .catch((caught: unknown) => live && setError(caught instanceof Error ? caught.message : 'Could not load the policy'));
    return () => {
      live = false;
    };
  }, [reset]);

  const currentSlug =
    policy?.unowned_findings_team && !policy.unowned_findings_team.deleted ? policy.unowned_findings_team.slug : '';
  const dirty = policy !== null && (catchAll !== currentSlug || requireOwner !== policy.require_owner_to_publish);
  React.useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const save = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      reset(await saveOwnershipPolicy({ unowned_findings_team: catchAll || null, require_owner_to_publish: requireOwner }));
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the policy');
    } finally {
      setSaving(false);
    }
  };

  const readOnly = !isAdmin;
  const deletedCatchAll = policy?.unowned_findings_team?.deleted ? policy.unowned_findings_team : null;

  return (
    <section aria-labelledby="tnt-ownership-heading" className="space-y-4" data-testid="tenant-ownership-policy">
      <div className="min-w-0">
        <h3 id="tnt-ownership-heading" className="tnt-section-title">
          Ownership
        </h3>
        <p className="tnt-section-desc">
          Who hears about findings on unowned APIs, and whether a project needs an owner team to publish.
        </p>
      </div>

      {readOnly ? (
        <p className="tnt-lock-note">
          <Lock className="size-[var(--icon-dense)] shrink-0" aria-hidden />
          Only administrators can change the ownership policy.
        </p>
      ) : null}
      {error ? <Alert variant="error">{error}</Alert> : null}

      {!policy && !error ? (
        <LoadingState message="Loading the ownership policy…" minHeightClassName="min-h-[8rem]" />
      ) : policy ? (
        <>
          <div className="space-y-2">
            <Label htmlFor="tnt-catch-all" className="block">
              Catch-all team
            </Label>
            <select
              id="tnt-catch-all"
              className="tnt-own-select"
              data-testid="tenant-catch-all"
              value={catchAll}
              disabled={readOnly || saving}
              onChange={(event) => {
                setCatchAll(event.target.value);
                setSaved(false);
              }}
            >
              <option value="">None — the Unowned findings report only</option>
              {teams.map((team) => (
                <option key={team.id} value={team.slug}>
                  {team.name}
                </option>
              ))}
            </select>
            <p className="tnt-section-desc">
              Findings on anything without a confirmed owner also go to this team&apos;s members and chat channel.
            </p>
            {deletedCatchAll ? (
              <Alert variant="warning" data-testid="tenant-catch-all-deleted">
                The catch-all team {deletedCatchAll.name} was deleted, so unowned findings reach nobody. Choose another
                team.
              </Alert>
            ) : null}
          </div>

          <div className="tnt-own-switch">
            <Switch
              id="tnt-require-owner"
              checked={requireOwner}
              disabled={readOnly || saving}
              onCheckedChange={(next) => {
                setRequireOwner(next);
                setSaved(false);
              }}
              data-testid="tenant-require-owner"
            />
            <div className="min-w-0">
              <Label htmlFor="tnt-require-owner">Require an owner to publish</Label>
              <p className="tnt-section-desc">
                A project with no confirmed owner team cannot publish a version (reason no-owner) unless it is
                force-published with a reason.
              </p>
            </div>
          </div>

          {readOnly ? null : (
            <div className="flex items-center gap-3">
              <Button onClick={() => void save()} disabled={!dirty || saving} data-testid="tenant-ownership-save">
                {saving ? 'Saving…' : 'Save changes'}
              </Button>
              {saved ? (
                <span className="tnt-section-desc" role="status">
                  Saved.
                </span>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

'use client';

/**
 * Workspace → Teams — `/ade/dashboard/teams` (CDG-2.4, #5963).
 *
 * Every team in the workspace: its name and handle, how many members it has, and the links people
 * use to reach it. The name opens the team page — members, what it owns and the findings routed to
 * it. Teams are created and changed with `apiome teams` or the REST API; this screen reads.
 *
 * Below the list (CDG-2.5): the workspace's **ownership policy**, read-only with a link to where it
 * is changed, and the **Ownership drift** report — entities whose owner team was deleted or has no
 * members, and suggestions nobody confirmed in 30 days.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Button, EmptyState, GatedState } from '@/app/components/ui';
import { useAuthSession } from '@lib/auth/session-client';
import {
  DRIFT_REASON_LABELS,
  OWNER_ENTITY_KIND_LABELS,
  ownedEntityHref,
  teamLinks,
  type OwnershipDrift,
  type OwnershipPolicy,
  type Team,
} from '@lib/owners';
import { fetchOwnershipDrift, fetchOwnershipPolicy, fetchTeams } from '@/app/components/ade/owners';

const HOME_ROUTE = '/ade/dashboard';

/**
 * The Teams list.
 *
 * @returns The page.
 */
export default function TeamsClient() {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [teams, setTeams] = React.useState<Team[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const [policy, setPolicy] = React.useState<OwnershipPolicy | null>(null);
  const [drift, setDrift] = React.useState<OwnershipDrift | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setTeams(await fetchTeams());
    } catch (caught) {
      setTeams(null);
      setError(caught instanceof Error ? caught.message : 'Could not load teams');
    }
    // The policy and the drift report are secondary: a failure leaves their sections out.
    fetchOwnershipPolicy().then(setPolicy).catch(() => setPolicy(null));
    fetchOwnershipDrift().then(setDrift).catch(() => setDrift(null));
  }, []);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Workspace' }, { label: 'Teams' }]}
        title="Teams"
        description="Groups that own catalog entities and hear about their findings."
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Teams belong to one workspace." />
        ) : error ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The teams could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : teams === null ? (
          <p className="tm-note" data-testid="teams-loading">
            Reading your teams…
          </p>
        ) : teams.length === 0 ? (
          <EmptyState
            variant="compact"
            surface={false}
            title="No teams yet"
            description="Create one with apiome teams create, then give it owners and members."
          />
        ) : (
          <div className="tm-table-wrap">
            <table className="tm-table" data-testid="teams-table">
              <caption className="sr-only">Teams in this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Team</th>
                  <th scope="col">Members</th>
                  <th scope="col">Links</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((team) => (
                  <tr key={team.id} data-testid={`team-row-${team.slug}`}>
                    <td>
                      <Link className="tm-name" href={`/ade/dashboard/teams/${encodeURIComponent(team.slug)}`}>
                        {team.name}
                      </Link>
                      <span className="tm-slug mono">{team.slug}</span>
                      {team.description ? <span className="tm-desc">{team.description}</span> : null}
                    </td>
                    <td className="tm-num">{team.member_count}</td>
                    <td>
                      <TeamLinks team={team} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tenantId && policy ? <PolicySummary policy={policy} /> : null}
        {tenantId && drift ? <DriftReport drift={drift} /> : null}
      </PageBody>
    </Page>
  );
}

/**
 * A team's contact, chat, on-call and docs links, or a dash.
 *
 * @param props - The team.
 * @returns The links.
 */
export function TeamLinks({ team }: { team: Team }) {
  const links = teamLinks(team);
  if (links.length === 0) return <span className="tm-muted">—</span>;
  return (
    <span className="tm-links">
      {links.map(([label, href]) => (
        <a key={label} className="tm-link" href={href} target={href.startsWith('mailto:') ? undefined : '_blank'} rel="noreferrer">
          {label}
        </a>
      ))}
    </span>
  );
}

/**
 * The ownership policy, read-only, with where to change it.
 *
 * @param props - The policy.
 * @returns The summary line.
 */
function PolicySummary({ policy }: { policy: OwnershipPolicy }) {
  const team = policy.unowned_findings_team;
  return (
    <section className="tm-section tm-policy" aria-labelledby="tm-policy" data-testid="teams-ownership-policy">
      <h2 id="tm-policy" className="tm-section__title">
        Ownership policy
      </h2>
      <p className="tm-muted">
        Catch-all team:{' '}
        <strong className="tm-strong">{team ? `${team.name}${team.deleted ? ' (deleted)' : ''}` : 'none'}</strong>
        {' · '}Require an owner to publish:{' '}
        <strong className="tm-strong">{policy.require_owner_to_publish ? 'on' : 'off'}</strong>
        {' · '}
        <Link className="tm-link" href="/ade/dashboard/tenants">
          Change it in the tenant’s Ownership settings
        </Link>
      </p>
    </section>
  );
}

/**
 * The Ownership drift report.
 *
 * @param props - The report.
 * @returns The section.
 */
function DriftReport({ drift }: { drift: OwnershipDrift }) {
  const reasons = Object.keys(DRIFT_REASON_LABELS) as Array<keyof typeof DRIFT_REASON_LABELS>;
  return (
    <section className="tm-section tm-policy" aria-labelledby="tm-drift" data-testid="ownership-drift">
      <h2 id="tm-drift" className="tm-section__title">
        Ownership drift
      </h2>
      {drift.items.length === 0 ? (
        <p className="tm-muted">No drift: every owner team has members, and no suggestion is older than {drift.stale_after_days} days.</p>
      ) : (
        reasons
          .filter((reason) => (drift.counts[reason] ?? 0) > 0)
          .map((reason) => (
            <div key={reason} className="tm-owned__group" data-testid={`ownership-drift-${reason}`}>
              <h3 className="tm-owned__kind">
                {DRIFT_REASON_LABELS[reason]} <span className="tm-muted">{drift.counts[reason]}</span>
              </h3>
              <ul className="tm-list">
                {drift.items
                  .filter((item) => item.reason === reason)
                  .map((item) => {
                    const href = ownedEntityHref({ kind: item.entity_kind, id: item.entity_id });
                    const name = item.entity_name || item.entity_id;
                    return (
                      <li key={`${reason}:${item.entity_kind}:${item.entity_id}:${item.team.slug}`} className="tm-list__row">
                        {href ? (
                          <Link className="tm-list__name" href={href}>
                            {name}
                          </Link>
                        ) : (
                          <span className="tm-list__name">{name}</span>
                        )}
                        <span className="tm-muted">
                          {OWNER_ENTITY_KIND_LABELS[item.entity_kind] ?? item.entity_kind} · {item.team.name || item.team.slug}
                        </span>
                      </li>
                    );
                  })}
              </ul>
            </div>
          ))
      )}
    </section>
  );
}

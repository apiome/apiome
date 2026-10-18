'use client';

/**
 * Workspace → Teams — `/ade/dashboard/teams` (CDG-2.4, #5963).
 *
 * Every team in the workspace: its name and handle, how many members it has, and the links people
 * use to reach it. The name opens the team page — members, what it owns and the findings routed to
 * it. Teams are created and changed with `apiome teams` or the REST API; this screen reads.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Button, EmptyState, GatedState } from '@/app/components/ui';
import { useAuthSession } from '@lib/auth/session-client';
import { teamLinks, type Team } from '@lib/owners';
import { fetchTeams } from '@/app/components/ade/owners';

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

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setTeams(await fetchTeams());
    } catch (caught) {
      setTeams(null);
      setError(caught instanceof Error ? caught.message : 'Could not load teams');
    }
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

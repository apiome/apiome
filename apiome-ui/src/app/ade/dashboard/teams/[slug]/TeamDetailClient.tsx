'use client';

/**
 * Workspace → Teams → one team — `/ade/dashboard/teams/[slug]` (CDG-2.4, #5963).
 *
 * Four things, in the order a team lead asks for them:
 *
 * 1. **Open findings** — the reader's unread owner-finding notifications routed to this team: the
 *    same rows the bell counts, so the two numbers always agree;
 * 2. **Members**, leads first, and the team's links;
 * 3. **What it owns**, grouped by kind, each linking to the entity;
 * 4. **The last 30 days** of findings routed to the team, one row per event.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Badge, Button, EmptyState, GatedState } from '@/app/components/ui';
import { useAuthSession } from '@lib/auth/session-client';
import { NOTIFICATION_TYPE_LABELS, isNotificationType, ownerFindingHref } from '@lib/notifications';
import {
  OWNER_ENTITY_KIND_LABELS,
  groupOwnedByKind,
  ownedEntityHref,
  ownerSourceLabel,
  type Team,
  type TeamActivity,
} from '@lib/owners';
import { fetchTeam, fetchTeamActivity } from '@/app/components/ade/owners';
import { formatRelativeWhen } from '@/app/components/ade/repositories/repositoryDetailModel';
import { TeamLinks } from '../TeamsClient';

const HOME_ROUTE = '/ade/dashboard';
const TEAMS_ROUTE = '/ade/dashboard/teams';
const NOTIFICATIONS_ROUTE = '/ade/dashboard/notifications';

/** Props for {@link TeamDetailClient}. */
export interface TeamDetailClientProps {
  /** The team's slug, from the route. */
  slug: string;
}

/**
 * The team page.
 *
 * @param props - See {@link TeamDetailClientProps}.
 * @returns The page.
 */
export default function TeamDetailClient({ slug }: TeamDetailClientProps) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [team, setTeam] = React.useState<Team | null>(null);
  const [activity, setActivity] = React.useState<TeamActivity | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [now] = React.useState(() => Date.now());

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const [nextTeam, nextActivity] = await Promise.all([fetchTeam(slug), fetchTeamActivity(slug)]);
      setTeam(nextTeam);
      setActivity(nextActivity);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the team');
    }
  }, [slug]);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  const title = team?.name ?? slug;

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Workspace' },
          { label: 'Teams', href: TEAMS_ROUTE },
          { label: title },
        ]}
        title={title}
        description={team?.description || 'Its members, what it owns and the findings routed to it.'}
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Teams belong to one workspace." />
        ) : error ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The team could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : !team || !activity ? (
          <p className="tm-note" data-testid="team-loading">
            Reading the team…
          </p>
        ) : (
          <div className="tm-detail" data-testid="team-detail">
            <section className="tm-facts" aria-label="At a glance">
              <Link className="tm-fact" href={NOTIFICATIONS_ROUTE} data-testid="team-open-findings">
                <span className="tm-fact__value">{activity.open_findings}</span>
                <span className="tm-fact__label">Open findings for you</span>
              </Link>
              <span className="tm-fact">
                <span className="tm-fact__value">{activity.owned.length}</span>
                <span className="tm-fact__label">Owned</span>
              </span>
              <span className="tm-fact">
                <span className="tm-fact__value">{activity.suggested_count}</span>
                <span className="tm-fact__label">Suggested</span>
              </span>
              <span className="tm-fact">
                <span className="tm-fact__value">{team.member_count}</span>
                <span className="tm-fact__label">Members</span>
              </span>
              <span className="tm-fact tm-fact--links">
                <TeamLinks team={team} />
              </span>
            </section>

            <section className="tm-section" aria-labelledby="tm-members">
              <h2 id="tm-members" className="tm-section__title">
                Members
              </h2>
              {team.members && team.members.length > 0 ? (
                <ul className="tm-list" data-testid="team-members">
                  {team.members.map((member) => (
                    <li key={member.user_id} className="tm-list__row">
                      <span className="tm-list__name">{member.name || member.email || member.user_id}</span>
                      {member.email && member.name ? <span className="tm-muted">{member.email}</span> : null}
                      {member.role === 'lead' ? <Badge variant="accent">Lead</Badge> : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="tm-muted">No members yet.</p>
              )}
            </section>

            <section className="tm-section" aria-labelledby="tm-owned">
              <h2 id="tm-owned" className="tm-section__title">
                What it owns
              </h2>
              {activity.owned.length === 0 ? (
                <p className="tm-muted">Nothing yet. Confirm a suggested owner, or assign one from a list.</p>
              ) : (
                <div className="tm-owned" data-testid="team-owned">
                  {groupOwnedByKind(activity.owned).map(([kind, entities]) => (
                    <div key={kind} className="tm-owned__group">
                      <h3 className="tm-owned__kind">
                        {OWNER_ENTITY_KIND_LABELS[kind]} <span className="tm-muted">{entities.length}</span>
                      </h3>
                      <ul className="tm-list">
                        {entities.map((entity) => {
                          const href = ownedEntityHref(entity);
                          return (
                            <li key={`${entity.kind}:${entity.id}`} className="tm-list__row">
                              {href ? (
                                <Link className="tm-list__name" href={href}>
                                  {entity.name}
                                </Link>
                              ) : (
                                <span className="tm-list__name">{entity.name}</span>
                              )}
                              <span className="tm-muted">{ownerSourceLabel(entity.source)}</span>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="tm-section" aria-labelledby="tm-events">
              <h2 id="tm-events" className="tm-section__title">
                Findings routed in the last 30 days
              </h2>
              {activity.events.length === 0 ? (
                <p className="tm-muted">No findings reached this team in the last 30 days.</p>
              ) : (
                <ul className="tm-list" data-testid="team-events">
                  {activity.events.map((event, index) => {
                    const href = ownerFindingHref(event.link ?? undefined);
                    const label = isNotificationType(event.type) ? NOTIFICATION_TYPE_LABELS[event.type] : event.type;
                    const when = event.created_at ? formatRelativeWhen(event.created_at, now) : '';
                    return (
                      <li key={`${event.type}:${event.entity_id}:${event.created_at}:${index}`} className="tm-list__row">
                        <Badge variant="neutral">{label}</Badge>
                        {href ? (
                          <Link className="tm-list__name" href={href}>
                            {event.summary || label}
                          </Link>
                        ) : (
                          <span className="tm-list__name">{event.summary || label}</span>
                        )}
                        <span className="tm-muted">
                          {[event.entity_name, when].filter(Boolean).join(' · ')}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>
        )}
      </PageBody>
    </Page>
  );
}

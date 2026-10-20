'use client';

/**
 * Bring in → Catalog → one **component** — `/ade/dashboard/catalog/components/[slug]` (CDG-5.5, #5983).
 *
 * A Backstage component, system or domain, or a Compass component, that someone accepted from an
 * import report: its type and lifecycle, the system or domain it belongs to, its links, its owner
 * (imported owners arrive as suggestions to confirm) and its catalog facts. Its declared
 * dependencies are on the dependency graph.
 */

import * as React from 'react';
import Link from 'next/link';
import { ExternalLink, RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Badge, Button, EmptyState, GatedState, LoadingState } from '@/app/components/ui';
import { EntityOwnerSection } from '@/app/components/ade/catalogAgents/EntityOwnerSection';
import { CatalogFactsPanel } from '@/app/components/ade/catalogFacts/CatalogFactsPanel';
import { fetchComponent } from '@/app/components/ade/catalogMigrations/catalogMigrationsApi';
import { useAuthSession } from '@lib/auth/session-client';
import {
  COMPONENT_CATEGORY_LABELS,
  LINK_TYPE_LABELS,
  MIGRATION_SOURCE_LABELS,
  type CatalogComponent,
} from '@lib/catalog-migrations';
import { graphPageHref } from '@lib/graph';

const HOME_ROUTE = '/ade/dashboard';
const CATALOG_ROUTE = '/ade/dashboard/catalog';
const COMPONENTS_ROUTE = '/ade/dashboard/catalog?kind=component';

/** Props for {@link ComponentDetailClient}. */
export interface ComponentDetailClientProps {
  /** The component's slug (or id), from the route. */
  slug: string;
}

/**
 * The component page.
 *
 * @param props - See {@link ComponentDetailClientProps}.
 * @returns The page.
 */
export default function ComponentDetailClient({ slug }: ComponentDetailClientProps) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [component, setComponent] = React.useState<CatalogComponent | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setComponent(await fetchComponent(slug));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the component');
    }
  }, [slug]);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  const title = component?.name ?? slug;
  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Bring in' },
          { label: 'Catalog', href: CATALOG_ROUTE },
          { label: 'Components', href: COMPONENTS_ROUTE },
          { label: title },
        ]}
        title={title}
        description={component?.description || 'A component brought in from Backstage or Compass.'}
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Components belong to one workspace." />
        ) : error && !component ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The component could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : !component ? (
          <LoadingState message="Reading the component…" minHeightClassName="min-h-[8rem]" />
        ) : (
          <div className="agt-page" data-testid="component-detail">
            <dl className="agt-facts">
              <div>
                <dt>Kind</dt>
                <dd>
                  <Badge variant="neutral">{COMPONENT_CATEGORY_LABELS[component.category]}</Badge>
                </dd>
              </div>
              <div>
                <dt>Type</dt>
                <dd>{component.componentType ?? '—'}</dd>
              </div>
              <div>
                <dt>Lifecycle</dt>
                <dd>{component.lifecycle ?? '—'}</dd>
              </div>
              <div>
                <dt>Part of</dt>
                <dd className="mono">{component.parentRef ?? '—'}</dd>
              </div>
              <div>
                <dt>Imported from</dt>
                <dd>
                  {MIGRATION_SOURCE_LABELS[component.source]} · <span className="mono">{component.externalRef}</span>
                </dd>
              </div>
            </dl>

            <section className="agt-section" aria-labelledby="cmp-links" data-testid="component-links">
              <h2 id="cmp-links" className="agt-section__title">
                Links
              </h2>
              {component.links.length === 0 ? (
                <p className="agt-muted">No links were imported.</p>
              ) : (
                <ul className="agt-list">
                  {component.links.map((link) => (
                    <li key={`${link.type}-${link.url}`} className="mig-link">
                      <Badge variant="neutral">{LINK_TYPE_LABELS[link.type]}</Badge>
                      <a className="agt-link agt-inline-icon" href={link.url} target="_blank" rel="noreferrer noopener">
                        {link.title || link.url}
                        <ExternalLink aria-hidden />
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <EntityOwnerSection kind="component" entityId={component.id} owner={component.owner} onChanged={() => void load()} />
            <CatalogFactsPanel kind="component" id={component.id} />

            <section className="agt-section" aria-labelledby="cmp-graph">
              <h2 id="cmp-graph" className="agt-section__title">
                Dependencies
              </h2>
              <p className="agt-muted">
                What it depends on and consumes, as declared in {MIGRATION_SOURCE_LABELS[component.source]}.{' '}
                <Link className="agt-link" href={graphPageHref('component', component.id)}>
                  Open the dependency graph
                </Link>
              </p>
            </section>
          </div>
        )}
      </PageBody>
    </Page>
  );
}

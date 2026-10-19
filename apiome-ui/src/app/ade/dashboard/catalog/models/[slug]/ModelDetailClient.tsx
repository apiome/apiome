'use client';

/**
 * Bring in → Catalog → one model — `/ade/dashboard/catalog/models/[slug]` (CDG-5.2, #5980).
 *
 * The model's provider, name and version, where it is hosted, how it handles data, its owner and
 * every agent that runs on it. **Deprecated on** sets (or clears) the date that every one of those
 * agents shows; **Delete** removes the model (its agents keep running, with no model shown).
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Alert, Badge, Button, EmptyState, GatedState, Input, Label, LoadingState } from '@/app/components/ui';
import { EntityOwnerSection } from '@/app/components/ade/catalogAgents/EntityOwnerSection';
import { deleteModel, fetchModel, updateModel } from '@/app/components/ade/catalogAgents/catalogAgentsApi';
import { useAuthSession } from '@lib/auth/session-client';
import { MODEL_HOSTING_LABELS, agentHref, deprecationLabel, type CatalogModel } from '@lib/catalog-agents';

const HOME_ROUTE = '/ade/dashboard';
const CATALOG_ROUTE = '/ade/dashboard/catalog';
const MODELS_ROUTE = '/ade/dashboard/catalog?kind=model';

/** Props for {@link ModelDetailClient}. */
export interface ModelDetailClientProps {
  /** The model's slug (or id), from the route. */
  slug: string;
}

/** `YYYY-MM-DD` for a date input, from an ISO timestamp. */
function dateInputValue(iso: string | null): string {
  return iso ? iso.slice(0, 10) : '';
}

/**
 * The model page.
 *
 * @param props - See {@link ModelDetailClientProps}.
 * @returns The page.
 */
export default function ModelDetailClient({ slug }: ModelDetailClientProps) {
  const router = useRouter();
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [model, setModel] = React.useState<CatalogModel | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [deprecatedOn, setDeprecatedOn] = React.useState('');

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const next = await fetchModel(slug);
      setModel(next);
      setDeprecatedOn(dateInputValue(next.deprecatedAt));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the model');
    }
  }, [slug]);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  const saveDeprecation = async (value: string) => {
    if (!model) return;
    setBusy(true);
    setActionError(null);
    try {
      const next = await updateModel(model.slug, {
        deprecatedAt: value ? new Date(`${value}T00:00:00Z`).toISOString() : null,
      });
      setModel(next);
      setDeprecatedOn(dateInputValue(next.deprecatedAt));
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Could not save the model');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!model) return;
    setBusy(true);
    setActionError(null);
    try {
      await deleteModel(model.slug);
      router.push(MODELS_ROUTE);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Could not delete the model');
      setBusy(false);
    }
  };

  const title = model?.name ?? slug;
  const deprecation = model ? deprecationLabel(model) : null;

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Bring in' },
          { label: 'Catalog', href: CATALOG_ROUTE },
          { label: 'Models', href: MODELS_ROUTE },
          { label: title },
        ]}
        title={title}
        description="A model agents run on: where it is hosted and how it handles data."
        actions={
          model ? (
            <Button variant="danger-soft" disabled={busy} onClick={() => void remove()} data-testid="model-delete">
              Delete
            </Button>
          ) : null
        }
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Models belong to one workspace." />
        ) : error && !model ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The model could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : !model ? (
          <LoadingState message="Reading the model…" minHeightClassName="min-h-[8rem]" />
        ) : (
          <div className="agt-page" data-testid="model-detail">
            {actionError ? <Alert variant="error">{actionError}</Alert> : null}
            <dl className="agt-facts">
              <div>
                <dt>Provider</dt>
                <dd>{model.provider}</dd>
              </div>
              <div>
                <dt>Model</dt>
                <dd className="mono">
                  {model.modelName}
                  {model.modelVersion ? ` · ${model.modelVersion}` : ''}
                </dd>
              </div>
              <div>
                <dt>Hosting</dt>
                <dd>{MODEL_HOSTING_LABELS[model.hosting]}</dd>
              </div>
              <div>
                <dt>Deprecation</dt>
                <dd data-testid="model-deprecation">
                  {deprecation ? (
                    <Badge variant={model.deprecated ? 'danger' : 'warn'}>{deprecation}</Badge>
                  ) : (
                    'Not deprecated'
                  )}
                </dd>
              </div>
            </dl>

            <section className="agt-section" aria-labelledby="agt-data">
              <h2 id="agt-data" className="agt-section__title">
                Data handling
              </h2>
              <p className="agt-prose">{model.dataHandling || 'Not recorded.'}</p>
            </section>

            <EntityOwnerSection kind="model" entityId={model.id} owner={model.owner} onChanged={() => void load()} />

            <section className="agt-section" aria-labelledby="agt-deprecate">
              <h2 id="agt-deprecate" className="agt-section__title">
                Deprecation
              </h2>
              <div className="agt-owner">
                <Label htmlFor="agt-deprecated-on">Deprecated on</Label>
                <Input
                  id="agt-deprecated-on"
                  type="date"
                  className="agt-date"
                  value={deprecatedOn}
                  disabled={busy}
                  onChange={(event) => setDeprecatedOn(event.target.value)}
                  data-testid="model-deprecated-input"
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || deprecatedOn === dateInputValue(model.deprecatedAt)}
                  onClick={() => void saveDeprecation(deprecatedOn)}
                  data-testid="model-deprecated-save"
                >
                  Save date
                </Button>
                {model.deprecatedAt ? (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => void saveDeprecation('')} data-testid="model-deprecated-clear">
                    Clear
                  </Button>
                ) : null}
              </div>
              <p className="agt-muted">Every agent that runs on this model shows the date.</p>
            </section>

            <section className="agt-section" aria-labelledby="agt-agents" data-testid="model-agents">
              <h2 id="agt-agents" className="agt-section__title">
                Agents running on it
              </h2>
              {model.agents.length === 0 ? (
                <p className="agt-muted">No agent runs on this model yet.</p>
              ) : (
                <ul className="agt-list">
                  {model.agents.map((agent) => (
                    <li key={agent.id}>
                      <Link className="agt-link" href={agentHref(agent.slug)}>
                        {agent.name}
                      </Link>
                      {agent.status === 'retired' ? <span className="agt-muted"> · retired</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </PageBody>
    </Page>
  );
}

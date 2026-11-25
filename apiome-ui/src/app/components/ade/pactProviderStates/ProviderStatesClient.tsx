'use client';

/**
 * **Provider states** — `/ade/dashboard/pacts/provider-states` (PFX-3.3, #6933).
 *
 * For one provider: the states it has registered for the hosted Pact verifier (parameters,
 * default setup, per-target overrides) and the pre-run check of its pacts against them — every
 * state the pacts name, whether a run could set it up, and each problem that would hold an
 * interaction back. States are registered through the REST API; this page reads them.
 *
 * ### What this page owns
 *
 * The three reads and which provider is selected. How each half is drawn is
 * `ProviderStatesPanels`; the labels and REST paths are `@lib/pact-provider-states`. The first
 * provider is selected when the list arrives, so the page never opens on an empty half.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import type { ProviderOption, ProviderState, StateCheckResponse } from '@lib/pact-provider-states';
import { ProviderStateCheck, RegisteredStates } from './ProviderStatesPanels';
import { checkProviderStates, fetchProviderStates, fetchProviders } from './providerStatesApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/**
 * Turn a caught failure into the sentence to show.
 *
 * @param error - Whatever was caught.
 * @param fallback - What to say when the failure carried no message.
 * @returns The sentence.
 */
function describeFailure(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** One provider's two reads. */
interface ProviderView {
  states: ProviderState[];
  check: StateCheckResponse;
}

/**
 * The Provider states page.
 *
 * @returns The page.
 */
export default function ProviderStatesClient() {
  const [providers, setProviders] = React.useState<ProviderOption[] | null>(null);
  const [listError, setListError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [view, setView] = React.useState<ProviderView | null>(null);
  const [viewError, setViewError] = React.useState<string | null>(null);

  const loadProviders = React.useCallback(async () => {
    setListError(null);
    setProviders(null);
    try {
      const list = await fetchProviders();
      setProviders(list);
      setSelected((current) => current ?? list[0]?.slug ?? null);
    } catch (caught) {
      setListError(describeFailure(caught, 'Could not load the providers'));
    }
  }, []);

  const loadView = React.useCallback(async (provider: string) => {
    setView(null);
    setViewError(null);
    try {
      const [states, check] = await Promise.all([fetchProviderStates(provider), checkProviderStates(provider)]);
      setView({ states, check });
    } catch (caught) {
      setViewError(describeFailure(caught, 'Could not load the provider states'));
    }
  }, []);

  React.useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  React.useEffect(() => {
    if (selected) void loadView(selected);
  }, [selected, loadView]);

  return (
    <Page>
      <PageHeader
        title="Provider states"
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Provider states' }]}
        description="The states each provider can set up, checked against its pacts."
        actions={
          <Button variant="outline" onClick={() => (selected ? void loadView(selected) : void loadProviders())}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="pps" data-testid="pact-provider-states">
          {listError ? (
            <EmptyState
              variant="compact"
              tone="danger"
              title="The providers could not be read"
              description={listError}
              action={
                <Button variant="soft" onClick={() => void loadProviders()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : providers === null ? (
            <LoadingState message="Reading the providers…" minHeightClassName="min-h-[6rem]" />
          ) : providers.length === 0 ? (
            <EmptyState
              variant="compact"
              title="No providers yet"
              description="A provider appears here once a pact names it."
            />
          ) : (
            <>
              <ul className="pps__providers" aria-label="Providers">
                {providers.map((provider) => (
                  <li key={provider.slug}>
                    <button
                      type="button"
                      className="pps__provider"
                      aria-pressed={provider.slug === selected}
                      onClick={() => setSelected(provider.slug)}
                      data-testid={`pps-provider-${provider.slug}`}
                    >
                      {provider.name}
                    </button>
                  </li>
                ))}
              </ul>
              {viewError ? (
                <EmptyState
                  variant="compact"
                  tone="danger"
                  title="The provider states could not be read"
                  description={viewError}
                  action={
                    selected ? (
                      <Button variant="soft" onClick={() => void loadView(selected)}>
                        <RefreshCw aria-hidden />
                        Try again
                      </Button>
                    ) : undefined
                  }
                />
              ) : view ? (
                <div className="pps__panels">
                  <ProviderStateCheck check={view.check} />
                  <RegisteredStates states={view.states} />
                </div>
              ) : (
                <LoadingState message="Reading the provider states…" minHeightClassName="min-h-[6rem]" />
              )}
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}

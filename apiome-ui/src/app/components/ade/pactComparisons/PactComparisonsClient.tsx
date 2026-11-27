'use client';

/**
 * **Pact comparisons** — `/ade/dashboard/pacts/comparisons` (PFX-2.5, #6929).
 *
 * The workspace's most recent bi-directional comparisons (a consumer's pact against a provider's
 * OpenAPI contract, PFX-2.3), each row naming its verdict *with* its strength, and the fidelity
 * report of the one selected: what was compared, which matching rules were not supported, and
 * what could not be compared.
 *
 * ### What this page owns
 *
 * The two reads and which row is selected. How a report is drawn is `ComparisonFidelityReport`;
 * the labels and the rule that only a full comparison reads green are `@lib/pact-comparisons`.
 * The first row is selected when the list arrives, so the page never opens on an empty half.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  STRENGTH_TONES,
  VERDICT_TONES,
  summaryLine,
  verdictLabel,
  type ComparisonFidelityReport as Report,
  type ComparisonListEntry,
} from '@lib/pact-comparisons';
import { ComparisonFidelityReport } from './ComparisonFidelityReport';
import { fetchComparisonFidelity, fetchPactComparisons } from './pactComparisonsApi';

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

/**
 * The tone a row's verdict badge takes: green only for a pass compared in full.
 *
 * @param entry - The row.
 * @returns The badge tone.
 */
function rowTone(entry: Pick<ComparisonListEntry, 'verdict' | 'strength'>) {
  return entry.strength === 'full' ? VERDICT_TONES[entry.verdict] : STRENGTH_TONES[entry.strength];
}

/**
 * The Pact comparisons page.
 *
 * @returns The page.
 */
export default function PactComparisonsClient() {
  const [entries, setEntries] = React.useState<ComparisonListEntry[] | null>(null);
  const [listError, setListError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [report, setReport] = React.useState<Report | null>(null);
  const [reportError, setReportError] = React.useState<string | null>(null);

  const loadList = React.useCallback(async () => {
    setListError(null);
    setEntries(null);
    try {
      const list = await fetchPactComparisons();
      setEntries(list.comparisons);
      setSelected((current) => current ?? list.comparisons[0]?.id ?? null);
    } catch (caught) {
      setListError(describeFailure(caught, 'Could not load the comparisons'));
    }
  }, []);

  const loadReport = React.useCallback(async (id: string) => {
    setReport(null);
    setReportError(null);
    try {
      setReport(await fetchComparisonFidelity(id));
    } catch (caught) {
      setReportError(describeFailure(caught, 'Could not load the fidelity report'));
    }
  }, []);

  React.useEffect(() => {
    void loadList();
  }, [loadList]);

  React.useEffect(() => {
    if (selected) void loadReport(selected);
  }, [selected, loadReport]);

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="pacticipants" />}
        title="Pact comparisons"
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Contracts', href: CONTRACTS_ROUTE }, { label: 'Pact comparisons' }]}
        description="What each bi-directional comparison compared, and what it could not."
        actions={
          <Button variant="outline" onClick={() => void loadList()}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="pcl" data-testid="pact-comparisons">
          {listError ? (
            <EmptyState
              variant="compact"
              tone="danger"
              title="The comparisons could not be read"
              description={listError}
              action={
                <Button variant="soft" onClick={() => void loadList()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : entries === null ? (
            <LoadingState message="Reading the comparisons…" minHeightClassName="min-h-[6rem]" />
          ) : entries.length === 0 ? (
            <EmptyState
              variant="compact"
              title="No bi-directional comparisons yet"
              description="Comparisons run when a provider publishes its contract and a consumer its pact."
            />
          ) : (
            <>
              <ul className="pcl__list" aria-label="Recent comparisons">
                {entries.map((entry) => (
                  <li key={entry.id} className="pcl__item">
                    <button
                      type="button"
                      className="pcl__row"
                      aria-pressed={entry.id === selected}
                      onClick={() => setSelected(entry.id)}
                      data-testid={`pcl-row-${entry.id}`}
                    >
                      <span className="pcl__pair">
                        {entry.consumer.name}
                        {entry.consumer.version ? ` ${entry.consumer.version}` : ''} → {entry.provider.name}{' '}
                        {entry.provider.version}
                      </span>
                      <Badge variant={rowTone(entry)}>{verdictLabel(entry.verdict, entry.strength)}</Badge>
                      <span className="pcl__summary">{summaryLine(entry.summary)}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="pcl__report">
                {reportError ? (
                  <EmptyState
                    variant="compact"
                    tone="danger"
                    title="The fidelity report could not be read"
                    description={reportError}
                    action={
                      selected ? (
                        <Button variant="soft" onClick={() => void loadReport(selected)}>
                          <RefreshCw aria-hidden />
                          Try again
                        </Button>
                      ) : undefined
                    }
                  />
                ) : report ? (
                  <ComparisonFidelityReport report={report} />
                ) : (
                  <LoadingState message="Reading the fidelity report…" minHeightClassName="min-h-[6rem]" />
                )}
              </div>
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}

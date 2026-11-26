'use client';

/**
 * **Matrix** — `/ade/dashboard/pacts/matrix` (PFX-5.4, #6948).
 *
 * The Pact Broker's matrix, asked from a query builder: one or more selectors (a pacticipant and
 * which of its versions — latest, one version, a branch, the main branch, a tag, an environment or
 * all), how rows collapse (`latestby`) and how many come back. **Show matrix** asks
 * `/api/pact/matrix`; the answer is the verdict explained, the grid of consumer versions ×
 * provider versions, and every row.
 *
 * The address follows the query (`q[0][pacticipant]=…`), so a matrix can be shared and reloaded;
 * an address the page cannot read says why and leaves the builder empty. A workspace with no
 * pacticipant shows the command that publishes the first pact.
 */

import * as React from 'react';
import Link from 'next/link';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE, PUBLISH_SNIPPET, type Pacticipant } from '@lib/pact-pacticipants';
import {
  CAN_I_DEPLOY_ROUTE,
  LATEST_BY_OPTIONS,
  MATRIX_LIMITS,
  MATRIX_ROUTE,
  MAX_SELECTORS,
  SELECTOR_SCOPES,
  describeSelector,
  emptyMatrixQuery,
  emptySelector,
  matrixQueryParams,
  matrixQueryProblem,
  parseMatrixQuery,
  scopeTakesLatest,
  scopeTakesValue,
  type LatestBy,
  type MatrixAnswer,
  type MatrixQuery,
  type MatrixSelector,
  type SelectorScope,
} from '@lib/pact-matrix';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { fetchPacticipants } from '../pactPacticipants/pacticipantsApi';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchEnvironmentNames, fetchMatrix } from './pactMatrixApi';
import { MatrixGridTable, MatrixRowsTable, VerdictPanel } from './MatrixPanels';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The id of the pacticipant suggestions. */
const PACTICIPANT_LIST_ID = 'pmx-pacticipant-options';

/** The id of the environment suggestions. */
const ENVIRONMENT_LIST_ID = 'pmx-environment-options';

/** One answer and the query it answers. */
interface Result {
  query: MatrixQuery;
  answer: MatrixAnswer | null;
  error: string | null;
}

/**
 * One selector's fields.
 *
 * @param props - The selector, its number, and how it changes or goes.
 * @returns The fieldset.
 */
function SelectorFields({
  selector,
  index,
  onChange,
  onRemove,
}: {
  selector: MatrixSelector;
  index: number;
  onChange: (next: MatrixSelector) => void;
  onRemove: (() => void) | null;
}) {
  const id = (field: string) => `pmx-selector-${index}-${field}`;
  const scopeLabel = SELECTOR_SCOPES.find((entry) => entry.scope === selector.scope)?.label ?? '';
  return (
    <fieldset className="pmx-selector" data-testid={`pmx-selector-${index}`}>
      <legend className="pmx-selector__legend">Selector {index + 1}</legend>
      <div className="pmx-selector__fields">
        <label className="pmx-field" htmlFor={id('pacticipant')}>
          <span className="ppx__field-label">Pacticipant</span>
          <input
            id={id('pacticipant')}
            className="pmx-input"
            list={PACTICIPANT_LIST_ID}
            value={selector.pacticipant}
            autoComplete="off"
            onChange={(event) => onChange({ ...selector, pacticipant: event.target.value })}
          />
        </label>
        <label className="pmx-field" htmlFor={id('scope')}>
          <span className="ppx__field-label">Versions</span>
          <select
            id={id('scope')}
            className="ppx__select"
            value={selector.scope}
            onChange={(event) =>
              onChange({
                ...selector,
                scope: event.target.value as SelectorScope,
                value: '',
                latest: false,
              })
            }
          >
            {SELECTOR_SCOPES.map((entry) => (
              <option key={entry.scope} value={entry.scope}>
                {entry.label}
              </option>
            ))}
          </select>
        </label>
        {scopeTakesValue(selector.scope) ? (
          <label className="pmx-field" htmlFor={id('value')}>
            <span className="ppx__field-label">{scopeLabel}</span>
            <input
              id={id('value')}
              className="pmx-input"
              list={selector.scope === 'environment' ? ENVIRONMENT_LIST_ID : undefined}
              value={selector.value}
              autoComplete="off"
              onChange={(event) => onChange({ ...selector, value: event.target.value })}
            />
          </label>
        ) : null}
        {scopeTakesLatest(selector.scope) ? (
          <label className="pmx-check" htmlFor={id('latest')}>
            <input
              id={id('latest')}
              type="checkbox"
              checked={selector.latest}
              onChange={(event) => onChange({ ...selector, latest: event.target.checked })}
            />
            Latest only
          </label>
        ) : null}
        {onRemove ? (
          <Button
            variant="ghost"
            type="button"
            onClick={onRemove}
            aria-label={`Remove selector ${index + 1}`}
          >
            <Trash2 aria-hidden />
            Remove
          </Button>
        ) : null}
      </div>
    </fieldset>
  );
}

/**
 * The Matrix page.
 *
 * @param props - `initialQuery`: the page address's query string.
 * @returns The page.
 */
export default function MatrixClient({ initialQuery }: { initialQuery: string }) {
  const initial = React.useMemo(
    () => parseMatrixQuery(new URLSearchParams(initialQuery)),
    [initialQuery],
  );
  const [draft, setDraft] = React.useState<MatrixQuery>(() =>
    initial.ok && initial.query.selectors.length > 0 ? initial.query : emptyMatrixQuery(),
  );
  const addressError = initial.ok ? null : initial.error;
  const [problem, setProblem] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<Result | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [pacticipants, setPacticipants] = React.useState<Pacticipant[] | null>(null);
  const [environments, setEnvironments] = React.useState<string[]>([]);

  const run = React.useCallback(async (query: MatrixQuery) => {
    setLoading(true);
    try {
      setResult({ query, answer: await fetchMatrix(query), error: null });
    } catch (caught) {
      setResult({
        query,
        answer: null,
        error: describeFailure(caught, 'Could not read the matrix'),
      });
    } finally {
      setLoading(false);
    }
  }, []);

  const submit = React.useCallback(
    (event?: React.FormEvent) => {
      event?.preventDefault();
      const found = matrixQueryProblem(draft);
      setProblem(found);
      if (found) return;
      window.history.replaceState(
        null,
        '',
        `${MATRIX_ROUTE}?${matrixQueryParams(draft).toString()}`,
      );
      void run(draft);
    },
    [draft, run],
  );

  React.useEffect(() => {
    // An address that carries a whole query is asked straight away.
    if (
      initial.ok &&
      initial.query.selectors.length > 0 &&
      matrixQueryProblem(initial.query) === null
    ) {
      void run(initial.query);
    }
  }, [initial, run]);

  React.useEffect(() => {
    // The suggestions are a convenience: a failure leaves the fields free text.
    fetchPacticipants()
      .then((page) => setPacticipants(page.pacticipants))
      .catch(() => setPacticipants(null));
    fetchEnvironmentNames()
      .then(setEnvironments)
      .catch(() => setEnvironments([]));
  }, []);

  const setSelector = (index: number, next: MatrixSelector) =>
    setDraft((query) => ({
      ...query,
      selectors: query.selectors.map((s, i) => (i === index ? next : s)),
    }));
  const removeSelector = (index: number) =>
    setDraft((query) => ({ ...query, selectors: query.selectors.filter((_, i) => i !== index) }));
  const addSelector = () =>
    setDraft((query) => ({ ...query, selectors: [...query.selectors, emptySelector()] }));

  const noPacticipants = pacticipants !== null && pacticipants.length === 0;

  return (
    <Page>
      <PageHeader
        title="Matrix"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: 'Matrix' },
        ]}
        description="Which consumer versions were verified against which provider versions, and whether they work together."
        actions={
          <Button variant="outline" asChild>
            <Link href={CAN_I_DEPLOY_ROUTE}>Can I deploy?</Link>
          </Button>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-matrix">
          <datalist id={PACTICIPANT_LIST_ID}>
            {(pacticipants ?? []).map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </datalist>
          <datalist id={ENVIRONMENT_LIST_ID}>
            {environments.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          {addressError ? (
            <p className="ppx__error" role="alert" data-testid="pmx-address-error">
              The address carries a query the matrix cannot read: {addressError}
            </p>
          ) : null}
          {noPacticipants ? (
            <div className="ppx__empty-note" data-testid="pmx-empty">
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="No pacticipants yet"
                description="The matrix lists pacts and their verification results. Publishing a pact registers its consumer and its provider. From the consumer's build, run:"
              />
              <CliSnippet label="Publish pacts" command={PUBLISH_SNIPPET} />
            </div>
          ) : null}
          <form
            className="ppx__panel"
            aria-labelledby="pmx-query-title"
            onSubmit={submit}
            data-testid="pmx-builder"
          >
            <div className="ppx__panel-head">
              <h2 id="pmx-query-title" className="ppx__title">
                Query
              </h2>
              <span className="ppx__meta">
                One selector shows its integrations; two or more ask whether those versions work
                together.
              </span>
            </div>
            {draft.selectors.map((selector, index) => (
              <SelectorFields
                key={index}
                selector={selector}
                index={index}
                onChange={(next) => setSelector(index, next)}
                onRemove={draft.selectors.length > 1 ? () => removeSelector(index) : null}
              />
            ))}
            <div className="ppx__toolbar">
              <Button
                variant="outline"
                type="button"
                onClick={addSelector}
                disabled={draft.selectors.length >= MAX_SELECTORS}
              >
                <Plus aria-hidden />
                Add selector
              </Button>
              <label className="ppx__field">
                <span className="ppx__field-label">Rows</span>
                <select
                  className="ppx__select"
                  value={draft.latestby ?? ''}
                  onChange={(event) =>
                    setDraft((query) => ({
                      ...query,
                      latestby: (event.target.value || null) as LatestBy | null,
                    }))
                  }
                  data-testid="pmx-latestby"
                >
                  {LATEST_BY_OPTIONS.map((option) => (
                    <option key={option.value ?? 'all'} value={option.value ?? ''}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="ppx__field">
                <span className="ppx__field-label">Limit</span>
                <select
                  className="ppx__select pmx-select--narrow"
                  value={draft.limit}
                  onChange={(event) =>
                    setDraft((query) => ({ ...query, limit: Number(event.target.value) }))
                  }
                  data-testid="pmx-limit"
                >
                  {(MATRIX_LIMITS as readonly number[]).includes(draft.limit) ? null : (
                    <option value={draft.limit}>{draft.limit} rows</option>
                  )}
                  {MATRIX_LIMITS.map((limit) => (
                    <option key={limit} value={limit}>
                      {limit} rows
                    </option>
                  ))}
                </select>
              </label>
              <Button variant="primary" type="submit" disabled={loading}>
                {loading ? 'Reading…' : 'Show matrix'}
              </Button>
            </div>
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="pmx-problem">
                {problem}
              </p>
            ) : null}
          </form>
          {result === null ? (
            loading ? (
              <LoadingState message="Reading the matrix…" minHeightClassName="min-h-[6rem]" />
            ) : noPacticipants ? null : (
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="Choose the versions to look at"
                description="Pick a pacticipant and which of its versions, then Show matrix. Add a second selector to ask whether two versions work together."
              />
            )
          ) : result.error ? (
            <EmptyState
              variant="compact"
              titleAs="h2"
              tone="danger"
              title="The matrix could not be read"
              description={result.error}
              action={
                <Button variant="soft" onClick={() => void run(result.query)}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : result.answer ? (
            <>
              <p className="ppx__meta" data-testid="pmx-asked">
                Asked about {result.query.selectors.map(describeSelector).join('; ')}.
              </p>
              <VerdictPanel
                answer={result.answer}
                limit={result.query.limit}
                onRecheck={() => void run(result.query)}
                rechecking={loading}
              />
              {result.answer.rows.length === 0 ? (
                <EmptyState
                  variant="compact"
                  titleAs="h2"
                  title="No rows"
                  description="No pact matches these selectors. Check the names and versions, or choose All versions."
                />
              ) : (
                <>
                  <section
                    className="ppx__panel"
                    aria-labelledby="pmx-grid-title"
                    data-testid="pmx-grid-panel"
                  >
                    <div className="ppx__panel-head">
                      <h2 id="pmx-grid-title" className="ppx__title">
                        Grid
                      </h2>
                      <span className="ppx__meta">
                        Each cell opens the pact of that consumer version.
                      </span>
                    </div>
                    <MatrixGridTable rows={result.answer.rows} />
                  </section>
                  <section className="ppx__panel" aria-labelledby="pmx-rows-title">
                    <div className="ppx__panel-head">
                      <h2 id="pmx-rows-title" className="ppx__title">
                        Rows
                      </h2>
                      <span className="ppx__meta" data-testid="pmx-row-total">
                        {result.answer.rows.length}{' '}
                        {result.answer.rows.length === 1 ? 'row' : 'rows'}
                      </span>
                    </div>
                    <MatrixRowsTable rows={result.answer.rows} caption="Every row of the matrix" />
                  </section>
                </>
              )}
            </>
          ) : null}
        </div>
      </PageBody>
    </Page>
  );
}

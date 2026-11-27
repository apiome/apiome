'use client';

/**
 * **Can I deploy** — `/ade/dashboard/pacts/can-i-deploy` (PFX-5.4, #6948).
 *
 * `pact-broker can-i-deploy` as a form: the pacticipant and version being deployed, where to (an
 * environment, or a tag — the legacy form), and pacticipants to leave out of the verdict. **Check**
 * asks `/api/pact/can-i-deploy`; the answer is the verdict explained (blocking notices with what to
 * do about each, warnings, passing), the rows it was reached from, and the `apiome pact
 * can-i-deploy` command that asks the same question in a pipeline. An unknown verdict offers
 * **Check again** with REST's `Retry-After`.
 *
 * The address follows the question (`?pacticipant=…&version=…&toEnvironment=…`), so a check can be
 * shared; an address that names the whole question is asked straight away. A workspace with no
 * pacticipant, and the page before a first check, show the CLI command.
 */

import * as React from 'react';
import { RefreshCw, X } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  PUBLISH_SNIPPET,
  isPacticipantHandle,
  type Pacticipant,
} from '@lib/pact-pacticipants';
import {
  CAN_I_DEPLOY_ROUTE,
  CAN_I_DEPLOY_SNIPPET,
  DEFAULT_MATRIX_LIMIT,
  MAX_IGNORED,
  canIDeployCommand,
  canIDeployFormFrom,
  canIDeployParams,
  parseCanIDeployQuery,
  type CanIDeployForm,
  type CanIDeployQuery,
  type MatrixAnswer,
} from '@lib/pact-matrix';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { fetchPacticipants, fetchVersions } from '../pactPacticipants/pacticipantsApi';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { fetchCanIDeploy, fetchEnvironmentNames } from './pactMatrixApi';
import { MatrixRowsTable, VerdictPanel } from './MatrixPanels';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** One answer and the question it answers. */
interface Result {
  query: CanIDeployQuery;
  form: CanIDeployForm;
  answer: MatrixAnswer | null;
  error: string | null;
}

/**
 * The Can I deploy page.
 *
 * @param props - `initialQuery`: the page address's query string.
 * @returns The page.
 */
export default function CanIDeployClient({ initialQuery }: { initialQuery: string }) {
  const initialParams = React.useMemo(() => new URLSearchParams(initialQuery), [initialQuery]);
  const [form, setForm] = React.useState<CanIDeployForm>(() => canIDeployFormFrom(initialParams));
  const [ignoreDraft, setIgnoreDraft] = React.useState('');
  const [problem, setProblem] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<Result | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [pacticipants, setPacticipants] = React.useState<Pacticipant[] | null>(null);
  const [environments, setEnvironments] = React.useState<string[] | null>(null);
  const [versions, setVersions] = React.useState<string[]>([]);

  const ask = React.useCallback(async (asked: CanIDeployForm) => {
    const parsed = parseCanIDeployQuery(canIDeployParams(asked));
    setProblem(parsed.ok ? null : parsed.error);
    if (!parsed.ok) return;
    setLoading(true);
    try {
      setResult({
        query: parsed.query,
        form: asked,
        answer: await fetchCanIDeploy(asked),
        error: null,
      });
    } catch (caught) {
      setResult({
        query: parsed.query,
        form: asked,
        answer: null,
        error: describeFailure(caught, 'Could not ask can-i-deploy'),
      });
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    // An address that names the whole question is asked straight away; one that carries
    // something else says why, rather than dropping it.
    if ([...initialParams.keys()].length === 0) return;
    const parsed = parseCanIDeployQuery(initialParams);
    if (parsed.ok) void ask(canIDeployFormFrom(initialParams));
    else setProblem(`The address carries a question that cannot be asked: ${parsed.error}`);
  }, [initialParams, ask]);

  React.useEffect(() => {
    // The pickers are conveniences: a failure leaves the fields free text.
    fetchPacticipants()
      .then((page) => setPacticipants(page.pacticipants))
      .catch(() => setPacticipants(null));
    fetchEnvironmentNames()
      .then(setEnvironments)
      .catch(() => setEnvironments(null));
  }, []);

  const pacticipant = form.pacticipant.trim();
  React.useEffect(() => {
    // Version suggestions for a pacticipant the workspace knows, latest first.
    setVersions([]);
    if (!isPacticipantHandle(pacticipant) || !pacticipants?.some((p) => p.slug === pacticipant))
      return;
    let live = true;
    fetchVersions(pacticipant)
      .then((page) => {
        if (live) setVersions(page.versions.map((version) => version.number));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [pacticipant, pacticipants]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const query = canIDeployParams(form).toString();
    window.history.replaceState(
      null,
      '',
      query ? `${CAN_I_DEPLOY_ROUTE}?${query}` : CAN_I_DEPLOY_ROUTE,
    );
    void ask(form);
  };

  const addIgnored = () => {
    const name = ignoreDraft.trim();
    if (!name) return;
    if (form.ignore.includes(name)) {
      setProblem(`${name} is already ignored.`);
      return;
    }
    if (form.ignore.length >= MAX_IGNORED) {
      setProblem(`At most ${MAX_IGNORED} pacticipants can be ignored.`);
      return;
    }
    setProblem(null);
    setForm({ ...form, ignore: [...form.ignore, name] });
    setIgnoreDraft('');
  };

  const noPacticipants = pacticipants !== null && pacticipants.length === 0;
  const environmentPicker =
    form.kind === 'environment' && environments !== null && environments.length > 0;

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="can-i-deploy" />}
        title="Can I deploy?"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Can I deploy?' },
        ]}
        description="Whether one version of a pacticipant is safe to deploy, and why."
      />
      <PageBody>
        <div className="ppx" data-testid="pact-can-i-deploy">
          <datalist id="pcd-pacticipant-options">
            {(pacticipants ?? []).map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </datalist>
          <datalist id="pcd-version-options">
            {versions.map((number) => (
              <option key={number} value={number} />
            ))}
          </datalist>
          {noPacticipants ? (
            <div className="ppx__empty-note" data-testid="pcd-empty">
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="No pacticipants yet"
                description="can-i-deploy reads pacts and their verification results. Publishing a pact registers its consumer and its provider. From the consumer's build, run:"
              />
              <CliSnippet label="Publish pacts" command={PUBLISH_SNIPPET} />
            </div>
          ) : null}
          <form
            className="ppx__panel"
            aria-labelledby="pcd-form-title"
            onSubmit={submit}
            data-testid="pcd-form"
          >
            <div className="ppx__panel-head">
              <h2 id="pcd-form-title" className="ppx__title">
                Question
              </h2>
            </div>
            <div className="pmx-selector__fields">
              <label className="pmx-field" htmlFor="pcd-pacticipant">
                <span className="ppx__field-label">Pacticipant</span>
                <input
                  id="pcd-pacticipant"
                  className="pmx-input"
                  list="pcd-pacticipant-options"
                  value={form.pacticipant}
                  autoComplete="off"
                  onChange={(event) => setForm({ ...form, pacticipant: event.target.value })}
                />
              </label>
              <label className="pmx-field" htmlFor="pcd-version">
                <span className="ppx__field-label">Version</span>
                <input
                  id="pcd-version"
                  className="pmx-input"
                  list="pcd-version-options"
                  value={form.version}
                  autoComplete="off"
                  onChange={(event) => setForm({ ...form, version: event.target.value })}
                />
              </label>
              <fieldset className="pmx-radios">
                <legend className="ppx__field-label">Deploy to</legend>
                <label className="pmx-check">
                  <input
                    type="radio"
                    name="pcd-kind"
                    checked={form.kind === 'environment'}
                    onChange={() => setForm({ ...form, kind: 'environment', destination: '' })}
                  />
                  Environment
                </label>
                <label className="pmx-check">
                  <input
                    type="radio"
                    name="pcd-kind"
                    checked={form.kind === 'tag'}
                    onChange={() => setForm({ ...form, kind: 'tag', destination: '' })}
                  />
                  Tag
                </label>
              </fieldset>
              <label className="pmx-field" htmlFor="pcd-destination">
                <span className="ppx__field-label">
                  {form.kind === 'environment' ? 'Environment' : 'Tag'}
                </span>
                {environmentPicker ? (
                  <select
                    id="pcd-destination"
                    className="ppx__select"
                    value={form.destination}
                    onChange={(event) => setForm({ ...form, destination: event.target.value })}
                  >
                    <option value="">Choose an environment</option>
                    {form.destination && !environments.includes(form.destination) ? (
                      <option value={form.destination}>
                        {form.destination} (not in this workspace)
                      </option>
                    ) : null}
                    {environments.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id="pcd-destination"
                    className="pmx-input"
                    value={form.destination}
                    autoComplete="off"
                    onChange={(event) => setForm({ ...form, destination: event.target.value })}
                  />
                )}
              </label>
            </div>
            <div className="pmx-selector__fields">
              <label className="pmx-field" htmlFor="pcd-ignore">
                <span className="ppx__field-label">Ignore a pacticipant</span>
                <input
                  id="pcd-ignore"
                  className="pmx-input"
                  list="pcd-pacticipant-options"
                  value={ignoreDraft}
                  autoComplete="off"
                  onChange={(event) => setIgnoreDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      addIgnored();
                    }
                  }}
                />
              </label>
              <Button
                variant="outline"
                type="button"
                onClick={addIgnored}
                disabled={!ignoreDraft.trim()}
              >
                Ignore
              </Button>
              {form.ignore.length > 0 ? (
                <ul
                  className="ppx__chips pmx-ignored"
                  aria-label="Ignored pacticipants"
                  data-testid="pcd-ignored"
                >
                  {form.ignore.map((name) => (
                    <li key={name}>
                      <button
                        type="button"
                        className="ppx__chip-button"
                        onClick={() =>
                          setForm({
                            ...form,
                            ignore: form.ignore.filter((other) => other !== name),
                          })
                        }
                        aria-label={`Stop ignoring ${name}`}
                      >
                        {name} <X aria-hidden className="pmx-chip-icon" />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            <div className="ppx__toolbar">
              <Button variant="primary" type="submit" disabled={loading}>
                {loading ? 'Checking…' : 'Check'}
              </Button>
            </div>
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="pcd-problem">
                {problem}
              </p>
            ) : null}
          </form>
          {result === null ? (
            loading ? (
              <LoadingState message="Asking can-i-deploy…" minHeightClassName="min-h-[6rem]" />
            ) : (
              <div className="ppx__empty-note" data-testid="pcd-start">
                <EmptyState
                  variant="compact"
                  titleAs="h2"
                  title="Ask about one version"
                  description="Name the pacticipant, its version and where it is going, then Check. A pipeline asks the same question with:"
                />
                <CliSnippet
                  label="Ask can-i-deploy from a pipeline"
                  command={CAN_I_DEPLOY_SNIPPET}
                />
              </div>
            )
          ) : result.error ? (
            <EmptyState
              variant="compact"
              titleAs="h2"
              tone="danger"
              title="can-i-deploy could not answer"
              description={result.error}
              action={
                <Button variant="soft" onClick={() => void ask(result.form)}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : result.answer ? (
            <>
              <p className="ppx__meta" data-testid="pcd-asked">
                Asked whether {result.query.pacticipant} {result.query.version} can be deployed{' '}
                {result.query.destination.kind === 'environment'
                  ? `to ${result.query.destination.name}`
                  : `with the tag ${result.query.destination.name}`}
                {result.query.ignore.length > 0
                  ? `, ignoring ${result.query.ignore.join(', ')}`
                  : ''}
                .
              </p>
              <VerdictPanel
                answer={result.answer}
                limit={DEFAULT_MATRIX_LIMIT}
                onRecheck={() => void ask(result.form)}
                rechecking={loading}
              />
              <section className="ppx__panel" aria-labelledby="pcd-rows-title">
                <div className="ppx__panel-head">
                  <h2 id="pcd-rows-title" className="ppx__title">
                    Rows the verdict was reached from
                  </h2>
                  <span className="ppx__meta" data-testid="pcd-row-total">
                    {result.answer.rows.length} {result.answer.rows.length === 1 ? 'row' : 'rows'}
                  </span>
                </div>
                {result.answer.rows.length === 0 ? (
                  <p className="ppx__muted">
                    No row: nothing in the destination depends on this version, and it depends on
                    nothing there.
                  </p>
                ) : (
                  <MatrixRowsTable
                    rows={result.answer.rows}
                    caption="The rows the verdict was reached from"
                  />
                )}
              </section>
              <section className="ppx__panel" aria-labelledby="pcd-cli-title" data-testid="pcd-cli">
                <div className="ppx__panel-head">
                  <h2 id="pcd-cli-title" className="ppx__title">
                    Ask from a pipeline
                  </h2>
                  <span className="ppx__meta">
                    Exits 0 when deployable, 1 otherwise. Reads PACT_BROKER_BASE_URL and
                    PACT_BROKER_TOKEN.
                  </span>
                </div>
                <CliSnippet
                  label="The same question from the CLI"
                  command={canIDeployCommand(result.query)}
                />
              </section>
            </>
          ) : null}
        </div>
      </PageBody>
    </Page>
  );
}

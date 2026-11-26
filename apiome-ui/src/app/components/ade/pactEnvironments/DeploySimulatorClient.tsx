'use client';

/**
 * **Deploy simulator** — `/ade/dashboard/pacts/environments/{name}/simulate` (PFX-5.7, #6951).
 *
 * *What if this version were deployed here?* Name a pacticipant, a version and (optionally) an
 * application instance, then **Simulate**. Nothing is recorded. The answer:
 *
 * * the candidate's own can-i-deploy verdict and what it would replace;
 * * **What else changes** — each version of a pacticipant it has a pact with, running here or
 *   deployed elsewhere (staging, say), with its verdict now and after: **Breaks** / **Fixes** a
 *   running one, **Clears** / **Blocks** a pending one (the predicted-clear look-ahead);
 * * **Not checked** — anything past the limit, with the reason (nothing is dropped);
 * * the pipeline commands that check and then record the same deployment.
 *
 * The address follows the question (`?pacticipant=…&version=…[&applicationInstance=…]`), so a
 * simulation can be shared; an address that names a whole question is asked straight away.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE, isPacticipantHandle, type Pacticipant } from '@lib/pact-pacticipants';
import {
  ENVIRONMENTS_ROUTE,
  environmentRoute,
  simulationCommands,
  simulationFormFrom,
  simulationFormProblem,
  simulationParams,
  simulatorRoute,
  type Simulation,
  type SimulationForm,
} from '@lib/pact-environments';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { fetchPacticipants, fetchVersions } from '../pactPacticipants/pacticipantsApi';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { SimulationResult } from './EnvironmentPanels';
import { fetchSimulation } from './environmentsApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** One answer and the question it answers. */
interface Result {
  form: SimulationForm;
  simulation: Simulation | null;
  error: string | null;
}

/**
 * The deploy simulator.
 *
 * @param props - `name`: the environment from the route; `initialQuery`: the address's query string.
 * @returns The page.
 */
export default function DeploySimulatorClient({ name, initialQuery }: { name: string; initialQuery: string }) {
  const initialParams = React.useMemo(() => new URLSearchParams(initialQuery), [initialQuery]);
  const [form, setForm] = React.useState<SimulationForm>(() => simulationFormFrom(initialParams));
  const [problem, setProblem] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<Result | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [pacticipants, setPacticipants] = React.useState<Pacticipant[] | null>(null);
  const [versions, setVersions] = React.useState<string[]>([]);

  const ask = React.useCallback(
    async (asked: SimulationForm) => {
      const refused = simulationFormProblem(asked);
      setProblem(refused);
      if (refused) return;
      setLoading(true);
      try {
        setResult({ form: asked, simulation: await fetchSimulation(name, asked), error: null });
      } catch (caught) {
        setResult({ form: asked, simulation: null, error: describeFailure(caught, 'Could not simulate the deployment') });
      } finally {
        setLoading(false);
      }
    },
    [name],
  );

  React.useEffect(() => {
    // An address that names a whole question is asked straight away; one that names part of a
    // question, or something else, says why rather than dropping it.
    if ([...initialParams.keys()].length === 0) return;
    const asked = simulationFormFrom(initialParams);
    const unknown = [...initialParams.keys()].find(
      (key) => !['pacticipant', 'version', 'applicationInstance'].includes(key),
    );
    if (unknown) setProblem(`The address carries a parameter the simulator does not take: ${unknown}.`);
    else void ask(asked);
  }, [initialParams, ask]);

  React.useEffect(() => {
    // The pickers are conveniences: a failure leaves the fields free text.
    fetchPacticipants()
      .then((page) => setPacticipants(page.pacticipants))
      .catch(() => setPacticipants(null));
  }, []);

  const pacticipant = form.pacticipant.trim();
  React.useEffect(() => {
    setVersions([]);
    if (!isPacticipantHandle(pacticipant) || !pacticipants?.some((p) => p.slug === pacticipant)) return;
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
    window.history.replaceState(null, '', simulatorRoute(name, simulationParams(form)));
    void ask(form);
  };

  return (
    <Page>
      <PageHeader
        title="Deploy simulator"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: 'Environments', href: ENVIRONMENTS_ROUTE },
          { label: name, href: environmentRoute(name) },
          { label: 'Simulate' },
        ]}
        description={`What deploying one version to ${name} would unblock or break — without deploying it.`}
      />
      <PageBody>
        <div className="ppx" data-testid="pact-deploy-simulator">
          <datalist id="psim-pacticipant-options">
            {(pacticipants ?? []).map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </datalist>
          <datalist id="psim-version-options">
            {versions.map((number) => (
              <option key={number} value={number} />
            ))}
          </datalist>
          <form className="ppx__panel" aria-labelledby="psim-form-title" onSubmit={submit} data-testid="psim-form">
            <div className="ppx__panel-head">
              <h2 id="psim-form-title" className="ppx__title">
                Deployment to simulate
              </h2>
              <span className="ppx__meta">Nothing is recorded.</span>
            </div>
            <div className="pmx-selector__fields">
              <label className="pmx-field" htmlFor="psim-pacticipant">
                <span className="ppx__field-label">Pacticipant</span>
                <input
                  id="psim-pacticipant"
                  className="pmx-input"
                  list="psim-pacticipant-options"
                  value={form.pacticipant}
                  autoComplete="off"
                  onChange={(event) => setForm({ ...form, pacticipant: event.target.value })}
                />
              </label>
              <label className="pmx-field" htmlFor="psim-version">
                <span className="ppx__field-label">Version</span>
                <input
                  id="psim-version"
                  className="pmx-input"
                  list="psim-version-options"
                  value={form.version}
                  autoComplete="off"
                  onChange={(event) => setForm({ ...form, version: event.target.value })}
                />
              </label>
              <label className="pmx-field" htmlFor="psim-instance">
                <span className="ppx__field-label">Application instance (optional)</span>
                <input
                  id="psim-instance"
                  className="pmx-input"
                  value={form.applicationInstance}
                  autoComplete="off"
                  placeholder="Unnamed"
                  onChange={(event) => setForm({ ...form, applicationInstance: event.target.value })}
                />
              </label>
            </div>
            <div className="ppx__toolbar">
              <Button variant="primary" type="submit" disabled={loading}>
                {loading ? 'Simulating…' : 'Simulate'}
              </Button>
            </div>
            {problem ? (
              <p className="ppx__error" role="alert" data-testid="psim-problem">
                {problem}
              </p>
            ) : null}
          </form>
          {result === null ? (
            loading ? (
              <LoadingState message="Simulating the deployment…" minHeightClassName="min-h-[6rem]" />
            ) : (
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="Try a deployment before you make it"
                description={`Name a version — one running in staging, say — and Simulate: the page says whether it can go to ${name}, and which versions it would clear the way for or break.`}
              />
            )
          ) : result.error ? (
            <EmptyState
              variant="compact"
              titleAs="h2"
              tone="danger"
              title="The deployment could not be simulated"
              description={result.error}
              action={
                <Button variant="soft" onClick={() => void ask(result.form)}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : result.simulation ? (
            <>
              <SimulationResult simulation={result.simulation} />
              <div className="ppx__toolbar">
                <Button variant="outline" onClick={() => void ask(result.form)} disabled={loading} data-testid="psim-recheck">
                  <RefreshCw aria-hidden />
                  {loading ? 'Checking…' : 'Check again'}
                </Button>
              </div>
              <section className="ppx__panel" aria-labelledby="psim-cli-title" data-testid="psim-cli">
                <div className="ppx__panel-head">
                  <h2 id="psim-cli-title" className="ppx__title">
                    Deploy from a pipeline
                  </h2>
                  <span className="ppx__meta">Records the deployment only when can-i-deploy says yes.</span>
                </div>
                <CliSnippet label="Check, then record the deployment" command={simulationCommands(result.simulation)} />
              </section>
            </>
          ) : null}
        </div>
      </PageBody>
    </Page>
  );
}

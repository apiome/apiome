/**
 * The two halves of the **Provider states** page (PFX-3.3, #6933): the pre-run check and the
 * registered states. Pure presentation — the page owns the reads.
 *
 * A problem reads as a badge *and* a sentence, a state the pacts name but the provider has not
 * registered is listed first (REST orders them), and "Ready" is only shown when nothing blocks.
 */

import * as React from 'react';
import { Badge } from '@/app/components/ui/Badge';
import {
  SETUP_KIND_LABELS,
  SEVERITY_TONES,
  checkStatement,
  parametersLine,
  setupLine,
  type ProviderState,
  type StateCheckEntry,
  type StateCheckResponse,
} from '@lib/pact-provider-states';

/**
 * One counter of the check's summary.
 *
 * @param props - The label and the value.
 * @returns The counter.
 */
function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div className="pps__counter" data-zero={value === 0 ? '' : undefined}>
      <dt className="pps__counter-label">{label}</dt>
      <dd className="pps__counter-value">{value}</dd>
    </div>
  );
}

/**
 * One state the selected pacts name, with its problems.
 *
 * @param props - The entry.
 * @returns The list item.
 */
function CheckEntry({ entry }: { entry: StateCheckEntry }) {
  return (
    <li className="pps__entry" data-registered={entry.registered ? 'true' : 'false'}>
      <div className="pps__entry-head">
        <span className="pps__state-name">{entry.name}</span>
        <Badge variant={entry.registered ? 'neutral' : 'danger'}>
          {entry.registered ? 'Registered' : 'Not registered'}
        </Badge>
        {entry.setup_kind ? (
          <span className="pps__meta">
            {SETUP_KIND_LABELS[entry.setup_kind]}
            {entry.overridden ? ' · target override' : ''}
          </span>
        ) : null}
        <span className="pps__meta">
          {entry.interactions} {entry.interactions === 1 ? 'interaction' : 'interactions'}
        </span>
      </div>
      {entry.problems.length > 0 ? (
        <ul className="pps__problems" aria-label={`Problems with ${entry.name}`}>
          {entry.problems.map((problem, index) => (
            <li
              key={`${problem.code}-${problem.parameter ?? ''}-${problem.interaction ?? ''}-${index}`}
              className="pps__problem"
              data-severity={problem.severity}
            >
              <Badge variant={SEVERITY_TONES[problem.severity]}>
                {problem.severity === 'blocking' ? 'Blocks' : 'Warning'}
              </Badge>
              <span className="pps__problem-message">{problem.message}</span>
              {problem.interaction ? (
                <span className="pps__meta">
                  {problem.consumer} · {problem.interaction}
                </span>
              ) : null}
              <code className="pps__code">{problem.code}</code>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * The pre-run check: whether a hosted verification could set up every state the pacts name.
 *
 * @param props - The check.
 * @returns The panel.
 */
export function ProviderStateCheck({ check }: { check: StateCheckResponse }) {
  return (
    <section className="pps__panel" aria-labelledby="pps-check-title" data-testid="pps-check">
      <div className="pps__panel-head">
        <h2 id="pps-check-title" className="pps__title">
          Before a run
        </h2>
        <Badge variant={check.ready ? 'ok' : 'danger'}>{check.ready ? 'Ready' : 'Not ready'}</Badge>
      </div>
      <p className="pps__statement" data-testid="pps-statement">
        {checkStatement(check)}
      </p>
      <dl className="pps__counters">
        <Counter label="Pacts" value={check.pacts} />
        <Counter label="States named" value={check.states.length} />
        <Counter label="Blocking" value={check.blocking} />
        <Counter label="Warnings" value={check.warnings} />
      </dl>
      {check.states.length > 0 ? (
        <ul className="pps__entries" aria-label="Provider states the pacts name">
          {check.states.map((entry) => (
            <CheckEntry key={entry.name} entry={entry} />
          ))}
        </ul>
      ) : null}
      {check.unused.length > 0 ? (
        <p className="pps__meta" data-testid="pps-unused">
          Registered but not named by any selected pact: {check.unused.join(', ')}
        </p>
      ) : null}
    </section>
  );
}

/**
 * The provider's registered states: parameters, default setup and per-target overrides.
 *
 * @param props - The states.
 * @returns The panel.
 */
export function RegisteredStates({ states }: { states: ProviderState[] }) {
  return (
    <section className="pps__panel" aria-labelledby="pps-registered-title" data-testid="pps-registered">
      <div className="pps__panel-head">
        <h2 id="pps-registered-title" className="pps__title">
          Registered states
        </h2>
        <span className="pps__meta">{states.length}</span>
      </div>
      {states.length === 0 ? (
        <p className="pps__statement">
          None yet. Register states with the REST API; until then, interactions that name a state are skipped.
        </p>
      ) : (
        <ul className="pps__entries" aria-label="Registered provider states">
          {states.map((state) => (
            <li key={state.id} className="pps__entry">
              <div className="pps__entry-head">
                <span className="pps__state-name">{state.name}</span>
              </div>
              {state.description ? <p className="pps__meta">{state.description}</p> : null}
              <dl className="pps__facts">
                <div className="pps__fact">
                  <dt>Parameters</dt>
                  <dd>{parametersLine(state.parameters)}</dd>
                </div>
                <div className="pps__fact">
                  <dt>Setup</dt>
                  <dd>{setupLine(state.setup)}</dd>
                </div>
                {state.overrides.map((override) => (
                  <div key={override.target_id} className="pps__fact">
                    <dt>On {override.target_slug}</dt>
                    <dd>{setupLine(override.setup)}</dd>
                  </div>
                ))}
              </dl>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

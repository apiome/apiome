'use client';

/**
 * **Provider test scaffolding** — the Export page's fourth kind (PFX-8.19, #7316):
 * `apiome pact scaffold-provider-tests`.
 *
 * Pick a provider and a language (pact-js, pact-jvm, pact-go, pact-python); **Write tests** asks REST
 * for a verification test wired to this broker — the broker from `PACT_BROKER_BASE_URL` /
 * `PACT_BROKER_TOKEN` (no secret in the file), the recommended selectors, pending pacts on — with a
 * stub per provider state the pacts name. The states table flags each state that has no handler in
 * Apiome (not registered under the provider's **Provider states**). A large file downloads without a
 * preview.
 */

import * as React from 'react';
import { Copy, Download, FlaskConical } from 'lucide-react';
import { Badge, Button, CommandBlock, Label, Switch } from '@/app/components/ui';
import { pactCommandSurfaces } from '@lib/pact-commands';
import {
  previewable,
  RECOMMENDED_SELECTORS_LABEL,
  SCAFFOLD_LANGUAGE_LABELS,
  SCAFFOLD_LANGUAGES,
  scaffoldAction,
  scaffoldSummary,
  sizeLabel,
  validateScaffold,
  type ProviderScaffold,
  type ScaffoldDraft,
  type ScaffoldLanguage,
} from '@lib/pact-export';
import { isFailure, saveFile, scaffoldTests } from './exportApi';
import { PacticipantField } from './PacticipantField';

/** Props of {@link ScaffoldPanel}. */
export interface ScaffoldPanelProps {
  draft: ScaffoldDraft;
  onDraft: (draft: ScaffoldDraft) => void;
  pacticipants: string[];
  onStatus: (status: { tone: 'warn' | 'danger'; text: string } | null) => void;
}

export function ScaffoldPanel({ draft, onDraft, pacticipants, onStatus }: ScaffoldPanelProps) {
  const [busy, setBusy] = React.useState(false);
  const [scaffold, setScaffold] = React.useState<ProviderScaffold | null>(null);
  const [copied, setCopied] = React.useState<string | null>(null);

  const edit = (patch: Partial<ScaffoldDraft>) => {
    onDraft({ ...draft, ...patch });
    if ('provider' in patch || 'language' in patch) {
      setScaffold(null);
      setCopied(null);
    }
  };

  const run = async () => {
    const problem = validateScaffold(draft);
    if (problem) return onStatus({ tone: 'danger', text: problem });
    onStatus(null);
    setBusy(true);
    const answer = await scaffoldTests(draft);
    setBusy(false);
    if (isFailure(answer)) {
      setScaffold(null);
      return onStatus({ tone: 'danger', text: answer.error });
    }
    setScaffold(answer);
  };

  const copy = async () => {
    if (!scaffold) return;
    try {
      await navigator.clipboard.writeText(scaffold.content);
      setCopied('Copied.');
    } catch {
      setCopied('Could not copy: download the file instead.');
    }
  };

  const unavailable = scaffold ? null : 'Write the tests first';

  return (
    <div className="ppub__split" data-testid="pexp-tests">
      <section className="ppub-card" aria-labelledby="pexp-tests-title">
        <div className="ppub-card__head">
          <h2 className="ppub-card__title" id="pexp-tests-title">
            Provider test scaffolding
          </h2>
          <Badge variant="warning">New</Badge>
        </div>
        <p className="ppub-card__lead">
          A provider team’s starting point: a verification test wired to this broker, with a stub for every provider state the pacts use.
        </p>
        <div className="ppub-grid">
          <PacticipantField id="pexp-tests-provider" label="Provider" value={draft.provider} options={pacticipants} onChange={(provider) => edit({ provider })} />
          <div className="ppub-field">
            <Label htmlFor="pexp-tests-language">Language</Label>
            <select id="pexp-tests-language" className="ppub-select" value={draft.language} onChange={(event) => edit({ language: event.target.value as ScaffoldLanguage })}>
              {SCAFFOLD_LANGUAGES.map((language) => (
                <option key={language} value={language}>
                  {SCAFFOLD_LANGUAGE_LABELS[language]}
                </option>
              ))}
            </select>
          </div>
          <div className="ppub-field">
            <span className="ppub-field__label">Pacts</span>
            <p className="ppub-hint" data-testid="pexp-tests-selectors">
              {RECOMMENDED_SELECTORS_LABEL}
            </p>
          </div>
        </div>
        <div className="ppub-switch">
          <div>
            <Label htmlFor="pexp-fail-unregistered">Fail if a state has no handler in Apiome</Label>
            <p className="ppub-hint" id="pexp-fail-unregistered-hint">
              In CI, exit non-zero when a state is not registered under the provider’s Provider states. Here, each one is flagged below.
            </p>
          </div>
          <Switch
            id="pexp-fail-unregistered"
            checked={draft.failOnUnregistered}
            aria-describedby="pexp-fail-unregistered-hint"
            onCheckedChange={(failOnUnregistered: boolean) => onDraft({ ...draft, failOnUnregistered })}
          />
        </div>
        <div className="ppub-row-actions">
          <Button variant="outline" onClick={() => void run()} disabled={busy} title={busy ? 'The tests are being written' : undefined} data-testid="pexp-tests-run">
            <FlaskConical aria-hidden />
            {busy ? 'Writing…' : scaffold ? 'Write again' : 'Write tests'}
          </Button>
        </div>
        {scaffold ? (
          <>
            {scaffold.states.length ? (
              <div className="ppub-table-wrap">
                <table className="ppub-table" data-testid="pexp-tests-states">
                  <thead>
                    <tr>
                      <th scope="col">Provider state</th>
                      <th scope="col">Parameters</th>
                      <th scope="col">In Apiome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scaffold.states.map((state) => (
                      <tr key={state.name} data-testid="pexp-tests-state">
                        <td>{state.name}</td>
                        <td className="pexp-source">{state.params.length ? state.params.join(', ') : '—'}</td>
                        <td>{state.registered ? <Badge variant="success">Registered</Badge> : <Badge variant="warning">No handler</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {scaffold.notices.length ? (
              <ul className="pexp-findings" data-testid="pexp-tests-notices">
                {scaffold.notices.map((notice, index) => (
                  <li key={index} className="pexp-finding">
                    <Badge variant={notice.code === 'provider-scaffold-state-left-out' ? 'danger' : 'warning'}>{notice.state ? 'State' : 'Note'}</Badge>
                    <span>
                      {notice.state ? `“${notice.state}”: ` : ''}
                      {notice.message}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}
      </section>

      <aside className="ppub__aside">
        <section className="ppub-card" aria-labelledby="pexp-tests-file">
          <div className="ppub-card__head">
            <h3 className="ppub-caps" id="pexp-tests-file">
              {scaffold ? scaffold.fileName : 'The test file'}
            </h3>
            {scaffold ? <span className="ppub-hint">{sizeLabel(scaffold.content.length)}</span> : null}
          </div>
          {!scaffold ? (
            <p className="ppub-hint">Write the tests to see them here.</p>
          ) : previewable(scaffold.content) ? (
            <pre className="pexp-preview" aria-label="Test file preview" tabIndex={0} data-testid="pexp-tests-preview">
              {scaffold.content}
            </pre>
          ) : (
            <p className="ppub-hint" data-testid="pexp-tests-large">
              This file is {sizeLabel(scaffold.content.length)} — too large to preview. Download it to read it.
            </p>
          )}
          <div className="ppub-row-actions">
            <Button onClick={() => scaffold && saveFile(scaffold.fileName, scaffold.content, 'text/plain')} disabled={!scaffold} title={unavailable ?? undefined} data-testid="pexp-tests-download">
              <Download aria-hidden />
              Download
            </Button>
            <Button variant="outline" onClick={() => void copy()} disabled={!scaffold} title={unavailable ?? undefined} data-testid="pexp-tests-copy">
              <Copy aria-hidden />
              Copy
            </Button>
            {scaffold ? (
              <span className="ppub-hint" data-testid="pexp-tests-summary">
                {scaffoldSummary(scaffold)}
              </span>
            ) : null}
          </div>
          {copied ? (
            <p className="ppub-hint" role="status">
              {copied}
            </p>
          ) : null}
          {scaffold ? (
            <p className="ppub-hint" data-testid="pexp-tests-install">
              Install: <code className="pexp-code">{scaffold.dependency}</code>. Set <code className="pexp-code">PACT_BROKER_BASE_URL</code>,{' '}
              <code className="pexp-code">PACT_BROKER_TOKEN</code> and <code className="pexp-code">PROVIDER_BASE_URL</code> where it runs.
            </p>
          ) : null}
        </section>
        <CommandBlock surfaces={pactCommandSurfaces(scaffoldAction(draft, '', scaffold?.fileName ?? null))} footnote="Replace {tenant} with your workspace’s handle in the REST path." data-testid="pexp-tests-command" />
      </aside>
    </div>
  );
}

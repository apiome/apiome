'use client';

/**
 * **Connect your pipelines** — section 3 of **Set up contracts** (PFX-8.20, #7317).
 *
 * One key, two variables; existing Pact tooling works unchanged.
 *
 * 1. **A key for CI** — creates an API key with the *Pact: consumer + deploy* scopes (publish pacts,
 *    read verdicts, record deployments) and shows it once. Its id and prefix are saved with the
 *    set-up, so a resume shows "created" instead of making a second key.
 * 2. **Where to point** — `PACT_BROKER_BASE_URL` and `PACT_BROKER_TOKEN`.
 * 3. **Add them to** — writes both as Actions secrets into the ticked GitHub repositories, with the
 *    account each was registered with. Each repository answers written, or skipped with the reason.
 *    Without a linked GitHub account this is two `gh secret set` lines to copy instead.
 *
 * A workspace that wired its pipelines some other way marks the section done by hand.
 */

import * as React from 'react';
import Link from 'next/link';
import { KeyRound } from 'lucide-react';
import { Button, Input } from '@/app/components/ui';
import { useAuthSession } from '@lib/auth/session-client';
import { scopesForApiKeyPreset } from '@/app/components/ade/apiKeys/apiKeysModel';
import { createApiKeyForTenant } from '@/app/components/ade/apiKeys/apiKeysApi';
import { ciKeyName, secretsSnippet, variablesText, type SecretsResult } from '@lib/pact-setup';
import type { SectionBodyProps } from './PacticipantsSection';
import { saveSetup, writeSecrets } from './setupApi';
import { AskAnAdmin, CopyBlock, SectionMessage } from './SetupSection';

/** Where keys are managed. */
export const API_KEYS_ROUTE = '/ade/dashboard/api-keys';

/** Props of {@link PipelinesSection}. */
export interface PipelinesSectionProps extends SectionBodyProps {
  /** The workspace's `PACT_BROKER_BASE_URL`, when it could be read. */
  brokerBaseUrl: string | null;
  /** The key created in this visit: held by the page so collapsing the section does not lose it. */
  secret: string | null;
  onSecret: (secret: string | null) => void;
}

/**
 * The section's body.
 *
 * @param props - The set-up, the broker address and the key created in this visit.
 * @returns The body.
 */
export function PipelinesSection({ state, onChanged, brokerBaseUrl, secret, onSecret }: PipelinesSectionProps) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const writable = state.github.repositories.filter((repository) => repository.linked);
  const [picked, setPicked] = React.useState<Set<string>>(() => new Set(writable.map((repository) => repository.id)));
  const [pasted, setPasted] = React.useState('');
  const [busy, setBusy] = React.useState<'key' | 'secrets' | 'mark' | null>(null);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [results, setResults] = React.useState<SecretsResult[] | null>(null);
  const saved = state.saved.ci_key;
  const token = secret ?? pasted.trim();
  const marked = state.saved.marked.includes('pipelines');

  const createKey = async () => {
    if (!tenantId) {
      setMessage({ tone: 'error', text: 'Select a workspace before creating a key.' });
      return;
    }
    setBusy('key');
    setMessage(null);
    try {
      const created = await createApiKeyForTenant({
        tenantId,
        name: ciKeyName(new Date()),
        description: 'Created by the Contracts set-up for CI: publish pacts, read verdicts, record deployments.',
        expiresInDays: null,
        scopes: scopesForApiKeyPreset('pact_publish'),
      });
      onSecret(created.secret);
      // The key exists now; if recording it fails the page says so rather than hiding the secret.
      try {
        if (created.id) await saveSetup({ ci_key: { id: created.id, prefix: created.keyPrefix || 'key' } });
        await onChanged();
        setMessage({ tone: 'ok', text: 'Key created. Copy it now: it is shown once.' });
      } catch (caught) {
        setMessage({
          tone: 'error',
          text: `The key was created but the set-up could not record it (${caught instanceof Error ? caught.message : 'unknown error'}). Copy it now.`,
        });
      }
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not create the key.' });
    } finally {
      setBusy(null);
    }
  };

  const write = async () => {
    setBusy('secrets');
    setMessage(null);
    setResults(null);
    try {
      const answer = await writeSecrets([...picked], token);
      setResults(answer);
      await onChanged();
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not write the secrets.' });
    } finally {
      setBusy(null);
    }
  };

  const mark = async (on: boolean) => {
    setBusy('mark');
    setMessage(null);
    try {
      await saveSetup({ mark: { pipelines: on } });
      await onChanged();
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not save.' });
    } finally {
      setBusy(null);
    }
  };

  const toggle = (id: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <div className="pset-body" data-testid="pset-pipelines-form">
      <p className="ppx__muted">One key, two variables. Existing Pact tooling works unchanged.</p>

      <h3 className="pcx-caps">1 · A key for CI</h3>
      {secret ? (
        <CopyBlock text={secret} label="The API key" testId="pset-key-secret" />
      ) : saved ? (
        <p className="pset-fact" data-testid="pset-key-saved">
          <KeyRound aria-hidden className="pset-fact__glyph" />
          Key <span className="pcx-mono">{saved.prefix}</span> was created for CI. Its value was shown once; manage it under{' '}
          <Link className="ppx__panel-link" href={API_KEYS_ROUTE}>
            API keys
          </Link>
          .
        </p>
      ) : null}
      <p className="ppx__muted">Scopes: publish pacts, read verdicts, record deployments. Shown once.</p>
      {state.can_edit && !secret ? (
        <div className="ppx__actions">
          <Button variant={saved ? 'outline' : 'default'} onClick={() => void createKey()} disabled={busy !== null} data-testid="pset-create-key">
            {busy === 'key' ? 'Creating…' : saved ? 'Create another key' : 'Create a key'}
          </Button>
        </div>
      ) : null}

      <h3 className="pcx-caps">2 · Where to point</h3>
      <CopyBlock text={variablesText(brokerBaseUrl)} label="The two variables" testId="pset-variables" />

      <h3 className="pcx-caps">3 · Add them to</h3>
      {state.github.linked ? (
        <>
          <div className="pset-checks" role="group" aria-label="Repositories">
            {state.github.repositories.map((repository) => {
              const inputId = `pset-repo-${repository.id}`;
              return (
                <label key={repository.id} htmlFor={inputId} className="pset-check" data-testid={inputId}>
                  <input
                    id={inputId}
                    type="checkbox"
                    checked={repository.linked && picked.has(repository.id)}
                    disabled={!repository.linked || busy !== null || !state.can_edit}
                    onChange={() => toggle(repository.id)}
                  />
                  <span className="pcx-mono">{repository.full_name}</span>
                  <span className="ppx__meta">
                    {!repository.linked
                      ? 'registered without a linked account: add the secrets by hand'
                      : repository.secrets_written_at
                        ? 'secrets written'
                        : 'secrets'}
                  </span>
                </label>
              );
            })}
          </div>
          {state.can_edit ? (
            <>
              {!secret ? (
                <div className="pset-inline">
                  <label htmlFor="pset-key-paste" className="pset-inline__label">
                    The key to store
                  </label>
                  <Input
                    id="pset-key-paste"
                    type="password"
                    autoComplete="off"
                    value={pasted}
                    onChange={(event) => setPasted(event.target.value)}
                    placeholder="Create a key above, or paste one"
                    disabled={busy !== null}
                    data-testid="pset-key-paste"
                  />
                </div>
              ) : null}
              <div className="ppx__actions">
                <Button
                  variant="outline"
                  onClick={() => void write()}
                  disabled={busy !== null || picked.size === 0 || token.length < 8}
                  data-testid="pset-write-secrets"
                >
                  {busy === 'secrets' ? 'Writing…' : `Write secrets to ${picked.size} ${picked.size === 1 ? 'repository' : 'repositories'}`}
                </Button>
              </div>
              <p className="ppx__muted">Uses the GitHub account each repository was registered with.</p>
            </>
          ) : null}
        </>
      ) : (
        <div data-testid="pset-secrets-snippet">
          <p className="ppx__muted">{state.github.reason ?? 'Apiome cannot write to a GitHub repository from this workspace.'}</p>
          <CopyBlock
            text={secretsSnippet(brokerBaseUrl, state.github.repositories[0]?.full_name ?? null)}
            label="Commands that set the two secrets"
            testId="pset-secrets-commands"
          />
          <p className="ppx__muted">Run them with the GitHub CLI, with the key in APIOME_API_KEY.</p>
        </div>
      )}
      {results ? (
        <ul className="pset-results" data-testid="pset-secrets-results">
          {results.map((result) => (
            <li key={result.repository_id} data-status={result.status}>
              <span className="pcx-mono">{result.full_name ?? result.repository_id}</span>{' '}
              {result.status === 'written' ? `— ${result.names.join(' and ')} written.` : `— not written. ${result.reason ?? ''}`}
            </li>
          ))}
        </ul>
      ) : null}
      <SectionMessage message={message} testId="pset-pipelines-message" />
      {state.can_edit ? (
        !saved || marked ? (
          <div className="ppx__actions">
            <Button variant="ghost" onClick={() => void mark(!marked)} disabled={busy !== null} data-testid="pset-pipelines-mark">
              {marked ? 'Not connected after all' : 'I connected them myself'}
            </Button>
          </div>
        ) : null
      ) : (
        <AskAnAdmin />
      )}
    </div>
  );
}

export default PipelinesSection;

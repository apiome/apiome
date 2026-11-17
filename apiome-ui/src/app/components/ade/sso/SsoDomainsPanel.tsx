'use client';

import * as React from 'react';
import { Plus, Trash2 } from 'lucide-react';

import { Alert, Badge, Button, FormField, Input } from '@/app/components/ui';
import {
  SSO_BUSY_REASON,
  ssoCheckHeading,
  type SsoDomainCheck,
  type WorkspaceSsoDomain,
  type WorkspaceSsoProvider,
} from '@lib/workspace-sso';
import { SsoCopyValue } from './SsoCopyValue';
import { addSsoDomain, removeSsoDomain, verifySsoDomain } from './workspaceSsoApi';

/** Props for {@link SsoDomainsPanel}. */
export interface SsoDomainsPanelProps {
  provider: WorkspaceSsoProvider;
  /** Told whenever the provider changed (a domain added, removed or verified). */
  onChange: (provider: WorkspaceSsoProvider) => void;
  /**
   * The last DNS check per domain, kept by the parent so a result stays on screen while the
   * drawer re-renders with the updated provider.
   */
  checks: Readonly<Record<string, SsoDomainCheck>>;
  onCheck: (domain: string, check: SsoDomainCheck) => void;
}

/**
 * The drawer's **Domains** tab (EID-1.2, #5012).
 *
 * The email domains this provider signs in. Adding one issues a DNS challenge: publish the token
 * as a TXT record at `_apiome-challenge.<domain>`, then press **Verify**. Only a verified domain
 * routes sign-ins. A check that could not be completed says so, with what the resolver answered —
 * it never reads as verified.
 *
 * @param props See {@link SsoDomainsPanelProps}.
 * @returns The panel.
 */
export function SsoDomainsPanel({ provider, onChange, checks, onCheck }: SsoDomainsPanelProps) {
  const [domain, setDomain] = React.useState('');
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  /** Run one request, holding the panel busy under `key` and showing a refusal's message. */
  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The request failed.');
    } finally {
      setBusy(null);
    }
  };

  const add = () =>
    run('add', async () => {
      onChange(await addSsoDomain(provider.id, domain));
      setDomain('');
    });

  const verify = (target: WorkspaceSsoDomain) =>
    run(`verify:${target.domain}`, async () => {
      const result = await verifySsoDomain(provider.id, target.domain);
      onCheck(target.domain, result.check);
      onChange(result.provider);
    });

  const remove = (target: WorkspaceSsoDomain) =>
    run(`remove:${target.domain}`, async () => onChange(await removeSsoDomain(provider.id, target.domain)));

  return (
    <div className="wsso-panel" data-testid="sso-domains-panel">
      <p className="wsso-note">
        People whose email is in a verified domain are sent to this provider when they sign in. A domain that is not
        verified routes no one.
      </p>

      {error ? (
        <Alert variant="error" data-testid="sso-domain-error">
          {error}
        </Alert>
      ) : null}

      {provider.domains.length === 0 ? (
        <p className="wsso-note" data-testid="sso-domains-empty">
          No domains yet. Add the domain your people’s email addresses use.
        </p>
      ) : (
        <ul className="wsso-domains">
          {provider.domains.map((entry) => {
            const check = checks[entry.domain];
            const heading = check ? ssoCheckHeading(check) : null;
            return (
              <li key={entry.domain} className="wsso-domain" data-testid={`sso-domain-${entry.domain}`}>
                <div className="wsso-domain__head">
                  <span className="wsso-domain__name mono">{entry.domain}</span>
                  {entry.verified ? (
                    <Badge variant="ok" dot>
                      Verified
                    </Badge>
                  ) : (
                    <Badge variant="warn" dot>
                      Not verified
                    </Badge>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="wsso-domain__remove"
                    disabled={busy !== null}
                    title={busy !== null ? SSO_BUSY_REASON : undefined}
                    aria-label={`Remove ${entry.domain}`}
                    onClick={() => void remove(entry)}
                  >
                    <Trash2 aria-hidden />
                    Remove
                  </Button>
                </div>

                {entry.verified ? null : (
                  <>
                    <p className="wsso-note">Add this TXT record at your DNS provider, then verify.</p>
                    <dl className="wsso-record">
                      <div className="wsso-record__row">
                        <dt>Type</dt>
                        <dd className="mono">TXT</dd>
                      </div>
                      <div className="wsso-record__row">
                        <dt>Name</dt>
                        <dd>
                          <SsoCopyValue label={`the record name for ${entry.domain}`} value={entry.record_name} />
                        </dd>
                      </div>
                      <div className="wsso-record__row">
                        <dt>Value</dt>
                        <dd>
                          <SsoCopyValue
                            label={`the record value for ${entry.domain}`}
                            value={entry.verification_token}
                          />
                        </dd>
                      </div>
                    </dl>
                    <div>
                      <Button
                        type="button"
                        variant="soft"
                        disabled={busy !== null}
                        title={busy !== null ? SSO_BUSY_REASON : undefined}
                        onClick={() => void verify(entry)}
                        data-testid={`sso-domain-verify-${entry.domain}`}
                      >
                        {busy === `verify:${entry.domain}` ? 'Checking DNS…' : 'Verify'}
                      </Button>
                    </div>
                  </>
                )}

                {check && heading && !(entry.verified && check.status !== 'verified') ? (
                  <Alert
                    variant={heading.tone}
                    role="status"
                    data-testid={`sso-domain-check-${entry.domain}`}
                    data-check-status={check.status}
                  >
                    {/* Not a heading: the result belongs to the domain row, not to the page outline. */}
                    <p className="wsso-check__title">{heading.title}</p>
                    <p>{check.message}</p>
                    {check.status !== 'verified' && check.observed.length > 0 ? (
                      <div className="wsso-observed">
                        <span className="wsso-observed__label">DNS answered</span>
                        <ul>
                          {check.observed.map((value, index) => (
                            <li key={`${index}:${value}`} className="mono">
                              {value}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </Alert>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <form
        className="wsso-add-domain"
        data-testid="sso-domain-add-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (busy === null && domain.trim()) void add();
        }}
      >
        <FormField label="Add a domain" htmlFor={`wsso-domain-${provider.id}`} className="wsso-add-domain__field">
          <Input
            id={`wsso-domain-${provider.id}`}
            className="mono"
            value={domain}
            placeholder="acme.com"
            disabled={busy !== null}
            autoComplete="off"
            onChange={(event) => setDomain(event.target.value)}
          />
        </FormField>
        <Button
          type="submit"
          variant="outline"
          disabled={busy !== null || domain.trim() === ''}
          title={busy !== null ? SSO_BUSY_REASON : domain.trim() === '' ? 'Type a domain first' : undefined}
        >
          <Plus aria-hidden />
          Add domain
        </Button>
      </form>
    </div>
  );
}

'use client';

/**
 * Step 1 of the **Migration wizard** — **Connect** (PFX-8.16, #7313), built to
 * `docs/mockups/contracts/migrate.html`.
 *
 * The broker's URL, how to sign in (an API token, or a username and password), and **Test
 * connection**, which says what was found (*PactFlow · 42 pacticipants found*) or why not (*Could not
 * sign in to acme.pactflow.io (401). Check the token.*). **Continue** stays disabled until a test has
 * passed; changing a field asks for a new test. The credentials are used for this migration only and
 * never stored.
 */

import * as React from 'react';
import Link from 'next/link';
import { CircleCheck, Globe } from 'lucide-react';
import { Button, FormField, Input } from '@/app/components/ui';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { formatCount, type SourceForm, type SourceTest } from '@lib/pact-migration';

/** Where **Test connection** stands. */
export type TestState =
  | { kind: 'idle' }
  | { kind: 'testing' }
  | { kind: 'ok'; result: SourceTest }
  | { kind: 'failed'; error: string };

/** Props for {@link ConnectStep}. */
export interface ConnectStepProps {
  form: SourceForm;
  onChange: (form: SourceForm) => void;
  test: TestState;
  onTest: () => void;
  /** Why the URL cannot be tested yet, if it cannot. */
  problem: string | null;
  /** Whether the viewer may migrate; without it every control is read-only. */
  canMigrate: boolean;
  /** Whether **Continue** is working (the dry run is being started). */
  busy: boolean;
  /** Why **Continue** failed, if it did. */
  error: string | null;
  onContinue: () => void;
}

/**
 * The credential fields for one way of signing in — shared with the **Copy** step, which asks for
 * them again before a resume.
 *
 * @param props - The form, its setter, an id prefix, whether the fields are read-only, and whether
 *   the credentials will be kept (keep-in-sync keeps them sealed while it is on — PFX-8.17).
 * @returns The token field, or the username and password fields.
 */
export function CredentialFields({
  form,
  onChange,
  idPrefix,
  disabled = false,
  kept = false,
}: {
  form: SourceForm;
  onChange: (form: SourceForm) => void;
  idPrefix: string;
  disabled?: boolean;
  kept?: boolean;
}) {
  const storage = kept
    ? 'Kept encrypted while keep-in-sync is on; deleted when it is off.'
    : 'Used for this migration only; not stored.';
  if (form.auth === 'token') {
    return (
      <FormField
        label="Token"
        htmlFor={`${idPrefix}-token`}
        helperText={`A read-only token is enough. ${storage}`}
      >
        <Input
          id={`${idPrefix}-token`}
          type="password"
          autoComplete="off"
          value={form.token}
          disabled={disabled}
          onChange={(event) => onChange({ ...form, token: event.target.value })}
          data-testid={`${idPrefix}-token`}
        />
      </FormField>
    );
  }
  return (
    <div className="pmg-pair">
      <FormField label="Username" htmlFor={`${idPrefix}-username`}>
        <Input
          id={`${idPrefix}-username`}
          autoComplete="off"
          value={form.username}
          disabled={disabled}
          onChange={(event) => onChange({ ...form, username: event.target.value })}
          data-testid={`${idPrefix}-username`}
        />
      </FormField>
      <FormField
        label="Password"
        htmlFor={`${idPrefix}-password`}
        helperText={storage}
      >
        <Input
          id={`${idPrefix}-password`}
          type="password"
          autoComplete="off"
          value={form.password}
          disabled={disabled}
          onChange={(event) => onChange({ ...form, password: event.target.value })}
          data-testid={`${idPrefix}-password`}
        />
      </FormField>
    </div>
  );
}

/**
 * The **Connect** step.
 *
 * @param props - See {@link ConnectStepProps}.
 * @returns The step's body and footer.
 */
export function ConnectStep({ form, onChange, test, onTest, problem, canMigrate, busy, error, onContinue }: ConnectStepProps) {
  const touched = form.source.trim().length > 0;
  return (
    <>
      <div className="pmg-body" data-testid="pmg-connect">
        <FormField
          label="Broker URL"
          htmlFor="pmg-source"
          helperText="Pact Broker (open source), PactFlow, or anything that speaks the Pact Broker HTTP API."
          error={touched && problem ? problem : undefined}
        >
          <div className="pmg-url">
            <Globe aria-hidden className="pmg-url__icon" />
            <Input
              id="pmg-source"
              type="url"
              inputMode="url"
              placeholder="https://acme.pactflow.io"
              value={form.source}
              disabled={!canMigrate}
              onChange={(event) => onChange({ ...form, source: event.target.value })}
              data-testid="pmg-source"
            />
          </div>
        </FormField>

        <div>
          <div className="pmg-label" id="pmg-auth-label">
            Sign in with
          </div>
          <div className="pcx-chips" role="group" aria-labelledby="pmg-auth-label">
            {(
              [
                ['token', 'API token'],
                ['basic', 'Username and password'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className="pcx-chip"
                aria-pressed={form.auth === value}
                disabled={!canMigrate}
                onClick={() => onChange({ ...form, auth: value })}
                data-testid={`pmg-auth-${value}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <CredentialFields form={form} onChange={onChange} idPrefix="pmg" disabled={!canMigrate} />

        <div className="pmg-test">
          <Button
            variant="outline"
            size="sm"
            onClick={onTest}
            disabled={!canMigrate || problem !== null || test.kind === 'testing'}
            data-testid="pmg-test"
          >
            {test.kind === 'testing' ? 'Testing…' : 'Test connection'}
          </Button>
          <span role="status" className="pmg-test__result" data-testid="pmg-test-result">
            {test.kind === 'ok' ? (
              <>
                <CircleCheck aria-hidden className="pmg-test__ok" />
                {test.result.product} · {formatCount(test.result.pacticipants)}{' '}
                {test.result.pacticipants === 1 ? 'pacticipant' : 'pacticipants'} found
              </>
            ) : null}
          </span>
        </div>
        {test.kind === 'failed' ? (
          <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pmg-test-error">
            {test.error}
          </p>
        ) : null}
        {error ? (
          <p className="ppub-hint ppub-hint--danger" role="alert" data-testid="pmg-connect-error">
            {error}
          </p>
        ) : null}
      </div>
      <div className="pmg-footer">
        <span className="pmg-footer__note">Your source is only read.</span>
        <Button variant="ghost" asChild>
          <Link href={CONTRACTS_ROUTE}>Cancel</Link>
        </Button>
        <Button onClick={onContinue} disabled={!canMigrate || test.kind !== 'ok' || busy} data-testid="pmg-continue">
          {busy ? 'Reading…' : 'Continue'}
        </Button>
      </div>
    </>
  );
}

export default ConnectStep;

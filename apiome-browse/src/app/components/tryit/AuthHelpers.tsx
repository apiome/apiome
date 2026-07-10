'use client';

import { useCallback, useId, useState, type ReactNode } from 'react';
import type {
  AuthCredentialValues,
  AuthCredentialsMap,
  OperationAuth,
  SupportedAuthScheme,
  UnsupportedAuthScheme,
} from '../../../../lib/tryit/auth';
import { shouldWarnProxyCredentials } from '../../../../lib/tryit/auth';

interface AuthHelpersProps {
  /** Resolved security for the current operation. */
  auth: OperationAuth;
  /** Current credential values keyed by scheme name. */
  credentials: AuthCredentialsMap;
  /** Persist a scheme's credential fields (caller also writes sessionStorage). */
  onChange: (schemeName: string, values: AuthCredentialValues) => void;
  /** True when the server picker is on the custom-URL slot. */
  isCustomHost: boolean;
}

/**
 * Scheme-aware auth inputs for the Try It panel — SIM-3.6 (#4452).
 *
 * Renders bearer / apiKey / basic helpers for the schemes the operation requires, with masked
 * inputs and a reveal toggle. Shows a red "credentials leave via proxy" notice when a custom
 * host is selected and any credential field is filled.
 */
export function AuthHelpers({ auth, credentials, onChange, isCustomHost }: AuthHelpersProps) {
  const idBase = useId();
  const showProxyWarning = shouldWarnProxyCredentials(
    isCustomHost,
    auth.schemes,
    credentials
  );

  if (!auth.applies && auth.unsupported.length === 0) {
    return null;
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
          Authentication
        </span>
        <span className="text-[10px] text-zinc-400 dark:text-zinc-500">
          Session only — cleared when the browser closes
        </span>
      </div>

      {showProxyWarning && (
        <p
          role="alert"
          className="mb-2 rounded-md border border-rose-300 bg-rose-50 px-2.5 py-2 text-[12px] font-medium text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300"
        >
          Credentials leave via proxy — this custom host is relayed through Apiome&apos;s Try It
          proxy (cookies stripped; credentials are not logged). Prefer a mock or spec server when
          possible.
        </p>
      )}

      {auth.schemes.length > 0 && (
        <ul className="space-y-3">
          {auth.schemes.map((scheme) => (
            <li key={scheme.name}>
              <SchemeFields
                scheme={scheme}
                values={credentials[scheme.name] ?? {}}
                onChange={onChange}
                idBase={idBase}
              />
            </li>
          ))}
        </ul>
      )}

      {auth.unsupported.length > 0 && (
        <UnsupportedNotice schemes={auth.unsupported} />
      )}
    </div>
  );
}

/** One scheme's labelled inputs (bearer token, apiKey, or basic username/password). */
function SchemeFields({
  scheme,
  values,
  onChange,
  idBase,
}: {
  scheme: SupportedAuthScheme;
  values: AuthCredentialValues;
  onChange: (schemeName: string, next: AuthCredentialValues) => void;
  idBase: string;
}) {
  const label = schemeLabel(scheme);
  const descriptionId = `${idBase}-${scheme.name}-desc`;

  return (
    <fieldset className="rounded-md border border-zinc-200 bg-white/60 p-2.5 dark:border-zinc-800 dark:bg-zinc-950/40">
      <legend className="px-1 font-mono text-[11px] font-medium text-zinc-700 dark:text-zinc-300">
        {scheme.name}
        <span className="ml-1.5 font-sans font-normal text-zinc-400 dark:text-zinc-500">
          ({label})
        </span>
      </legend>
      {scheme.description && (
        <p id={descriptionId} className="mb-2 text-[11px] text-zinc-500 dark:text-zinc-400">
          {scheme.description}
        </p>
      )}

      {scheme.kind === 'bearer' && (
        <MaskedField
          id={`${idBase}-${scheme.name}-token`}
          label={scheme.bearerFormat ? `Token (${scheme.bearerFormat})` : 'Bearer token'}
          value={values.bearerToken ?? ''}
          onChange={(bearerToken) => onChange(scheme.name, { ...values, bearerToken })}
          placeholder="eyJhbGciOi…"
          describedBy={scheme.description ? descriptionId : undefined}
        />
      )}

      {scheme.kind === 'apiKey' && (
        <>
          <MaskedField
            id={`${idBase}-${scheme.name}-key`}
            label={`${scheme.paramName} (${scheme.location})`}
            value={values.apiKey ?? ''}
            onChange={(apiKey) => onChange(scheme.name, { ...values, apiKey })}
            placeholder="Your API key"
            describedBy={scheme.description ? descriptionId : undefined}
          />
          {scheme.location === 'cookie' && (
            <p className="mt-1.5 text-[11px] text-amber-700 dark:text-amber-400">
              Cookie credentials are stripped by the Try It proxy — they only reach same-origin
              targets.
            </p>
          )}
        </>
      )}

      {scheme.kind === 'basic' && (
        <div className="grid gap-2 sm:grid-cols-2">
          <TextField
            id={`${idBase}-${scheme.name}-user`}
            label="Username"
            value={values.username ?? ''}
            onChange={(username) => onChange(scheme.name, { ...values, username })}
            autoComplete="username"
            describedBy={scheme.description ? descriptionId : undefined}
          />
          <MaskedField
            id={`${idBase}-${scheme.name}-pass`}
            label="Password"
            value={values.password ?? ''}
            onChange={(password) => onChange(scheme.name, { ...values, password })}
            autoComplete="current-password"
            describedBy={scheme.description ? descriptionId : undefined}
          />
        </div>
      )}
    </fieldset>
  );
}

/** Masked credential input with a show/hide toggle. */
function MaskedField({
  id,
  label,
  value,
  onChange,
  placeholder,
  autoComplete,
  describedBy,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  autoComplete?: string;
  describedBy?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  const toggle = useCallback(() => setRevealed((prev) => !prev), []);

  return (
    <div>
      <label htmlFor={id} className="mb-0.5 block text-[11px] text-zinc-500 dark:text-zinc-400">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          id={id}
          type={revealed ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete ?? 'off'}
          spellCheck={false}
          aria-describedby={describedBy}
          className="min-w-0 flex-1 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 font-mono text-[12px] text-zinc-800 shadow-xs focus:border-[var(--brand)] focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200"
        />
        <button
          type="button"
          onClick={toggle}
          aria-pressed={revealed}
          aria-label={revealed ? `Hide ${label}` : `Show ${label}`}
          className="shrink-0 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[11px] font-medium text-zinc-600 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          {revealed ? 'Hide' : 'Show'}
        </button>
      </div>
    </div>
  );
}

/** Plain text field (username). */
function TextField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  describedBy,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  autoComplete?: string;
  describedBy?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-0.5 block text-[11px] text-zinc-500 dark:text-zinc-400">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete ?? 'off'}
        spellCheck={false}
        aria-describedby={describedBy}
        className="w-full rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 font-mono text-[12px] text-zinc-800 shadow-xs focus:border-[var(--brand)] focus:outline-none dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-200"
      />
    </div>
  );
}

/** Notice for oauth / digest / unknown schemes the panel cannot collect. */
function UnsupportedNotice({ schemes }: { schemes: UnsupportedAuthScheme[] }) {
  const names: ReactNode[] = [];
  schemes.forEach((s, i) => {
    if (i > 0) names.push(i === schemes.length - 1 ? ' and ' : ', ');
    names.push(
      <span key={s.name} className="font-mono text-zinc-600 dark:text-zinc-300">
        {s.name}
      </span>
    );
  });
  const types = schemes.map((s) => (s.detail ? `${s.type}/${s.detail}` : s.type)).join(', ');

  return (
    <p className="mt-2 text-[11px] text-zinc-500 dark:text-zinc-400">
      This operation also references {names} ({types}), which is not supported by Try It auth
      helpers yet. Use Additional headers if you need to send credentials manually.
    </p>
  );
}

function schemeLabel(scheme: SupportedAuthScheme): string {
  if (scheme.kind === 'bearer') return 'HTTP bearer';
  if (scheme.kind === 'basic') return 'HTTP basic';
  return `apiKey · ${scheme.location}`;
}

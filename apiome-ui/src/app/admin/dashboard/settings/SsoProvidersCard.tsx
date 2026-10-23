'use client';

/**
 * Single sign-on card on System settings (EID-1.1, #5011).
 *
 * Lets an installation admin connect a workspace's own identity provider:
 *   - **Add identity provider** — OIDC by issuer (the discovery document is read and checked
 *     server-side) or SAML 2.0 by metadata URL or pasted XML; secrets are write-only;
 *   - per provider: the values to give the IdP (redirect URI, or ACS URL and SP entity ID), its
 *     email **domains** — add, **Mark verified** (on the admin's word; DNS verification arrives
 *     with the owner-facing page, EID-1.2), remove — and **Enable** / **Disable** / **Remove**.
 *
 * Sign-in routes to a provider only while it is enabled *and* has a verified domain ("Live").
 * Everything goes through the super-admin proxy (`/api/admin/sso/providers`), gated by the admin
 * session (OLO-8.1); refusals arrive with stable `sso-*` codes and their message is shown as is.
 */
import { useCallback, useEffect, useId, useState } from 'react';
import { AlertTriangle, Building2, Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react';

import {
  buildSsoCreatePayload,
  EMPTY_SSO_DRAFT,
  ssoAdminErrorMessage,
  ssoSetupDetails,
  suggestSsoSlug,
  type AdminSsoDraft,
  type AdminSsoProviderView,
} from '@lib/auth/admin-sso';
import { ICON_SIZE } from '@/app/components/ui/iconSizes';
import {
  INPUT_CLASSES,
  NEUTRAL_CHIP_CLASSES,
  PRIMARY_BUTTON_CLASSES,
  SECONDARY_BUTTON_CLASSES,
} from './settingsStyles';

/** Proxy route the card reads from and writes to. */
const SSO_PROVIDERS_URL = '/api/admin/sso/providers';

/** The green chip for a provider sign-ins reach. */
const LIVE_CHIP_CLASSES =
  'inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-2xs font-medium text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-400';

/** The amber chip for an enabled provider with no verified domain yet. */
const WAITING_CHIP_CLASSES =
  'inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-2xs font-medium text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-400';

/**
 * Whether a list row has the shape the card renders (an id, a slug and a domains array).
 *
 * @param value One element of the proxy's `providers` array.
 * @returns True for a renderable provider.
 */
function isProviderView(value: unknown): value is AdminSsoProviderView {
  const row = value as Partial<AdminSsoProviderView> | null;
  return Boolean(row && typeof row.id === 'string' && typeof row.slug === 'string' && Array.isArray(row.domains));
}

/** Inline error box, matching the other settings cards. */
function ErrorNote({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </p>
  );
}

/**
 * Send one request through the proxy.
 *
 * @returns `{ ok, status, body }` — never throws.
 */
async function call(path: string, init: { method: string; body?: unknown } = { method: 'GET' }) {
  try {
    const response = await fetch(`${SSO_PROVIDERS_URL}${path}`, {
      method: init.method,
      headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      cache: 'no-store',
    });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { ok: response.ok, status: response.status, body };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

/** A labelled text field. */
function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-slate-700 dark:text-slate-200">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-slate-600 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

/** The add-provider form. */
function AddProviderForm({ onAdded, onCancel }: { onAdded: (view: AdminSsoProviderView) => void; onCancel: () => void }) {
  const ids = useId();
  const [draft, setDraft] = useState<AdminSsoDraft>(EMPTY_SSO_DRAFT);
  const [slugEdited, setSlugEdited] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof AdminSsoDraft>(key: K, value: AdminSsoDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const result = await call('', { method: 'POST', body: buildSsoCreatePayload(draft) });
    setSaving(false);
    if (!result.ok) {
      setError(ssoAdminErrorMessage(result.status, result.body, 'The identity provider could not be added.'));
      return;
    }
    onAdded(result.body as AdminSsoProviderView);
  };

  return (
    <form
      onSubmit={submit}
      aria-label="Add identity provider"
      className="flex flex-col gap-4 rounded-md border border-slate-200 p-4 dark:border-slate-700"
      data-testid="sso-add-form"
    >
      <fieldset disabled={saving}>
        <legend className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">Protocol</legend>
        <div className="flex gap-4">
          {(['oidc', 'saml'] as const).map((protocol) => (
            <label key={protocol} className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
              <input
                type="radio"
                name={`${ids}-protocol`}
                value={protocol}
                checked={draft.protocol === protocol}
                onChange={() => set('protocol', protocol)}
                className="accent-indigo-600"
              />
              {protocol === 'oidc' ? 'OIDC' : 'SAML 2.0'}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field id={`${ids}-name`} label="Name">
          <input
            id={`${ids}-name`}
            className={INPUT_CLASSES}
            value={draft.displayName}
            required
            placeholder="Acme Okta"
            onChange={(e) => {
              set('displayName', e.target.value);
              if (!slugEdited) set('slug', suggestSsoSlug(e.target.value));
            }}
          />
        </Field>
        <Field id={`${ids}-slug`} label="ID" hint="Lower-case letters, digits and hyphens. Appears in sign-in URLs.">
          <input
            id={`${ids}-slug`}
            className={`${INPUT_CLASSES} font-mono`}
            value={draft.slug}
            required
            maxLength={28}
            placeholder="acme-okta"
            onChange={(e) => {
              setSlugEdited(true);
              set('slug', e.target.value);
            }}
          />
        </Field>
      </div>

      <Field id={`${ids}-tenant`} label="Workspace ID (optional)" hint="The workspace this IdP signs people in to.">
        <input
          id={`${ids}-tenant`}
          className={`${INPUT_CLASSES} font-mono`}
          value={draft.tenantId}
          placeholder="00000000-0000-0000-0000-000000000000"
          onChange={(e) => set('tenantId', e.target.value)}
        />
      </Field>

      {draft.protocol === 'oidc' ? (
        <>
          <Field id={`${ids}-issuer`} label="Issuer URL" hint="Apiome reads /.well-known/openid-configuration from it.">
            <input
              id={`${ids}-issuer`}
              type="url"
              className={INPUT_CLASSES}
              value={draft.issuer}
              required
              placeholder="https://acme.okta.com"
              onChange={(e) => set('issuer', e.target.value)}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id={`${ids}-client`} label="Client ID">
              <input
                id={`${ids}-client`}
                className={`${INPUT_CLASSES} font-mono`}
                value={draft.clientId}
                required
                onChange={(e) => set('clientId', e.target.value)}
              />
            </Field>
            <Field id={`${ids}-secret`} label="Client secret" hint="Stored encrypted. Never shown again.">
              <input
                id={`${ids}-secret`}
                type="password"
                autoComplete="off"
                className={`${INPUT_CLASSES} font-mono`}
                value={draft.clientSecret}
                required
                onChange={(e) => set('clientSecret', e.target.value)}
              />
            </Field>
          </div>
        </>
      ) : (
        <>
          <Field id={`${ids}-metadata-url`} label="IdP metadata URL" hint="Or paste the metadata XML below.">
            <input
              id={`${ids}-metadata-url`}
              type="url"
              className={INPUT_CLASSES}
              value={draft.metadataUrl}
              placeholder="https://idp.example.com/saml/metadata"
              onChange={(e) => set('metadataUrl', e.target.value)}
            />
          </Field>
          <Field id={`${ids}-metadata-xml`} label="IdP metadata XML">
            <textarea
              id={`${ids}-metadata-xml`}
              rows={4}
              spellCheck={false}
              className={`${INPUT_CLASSES} font-mono`}
              value={draft.metadataXml}
              onChange={(e) => set('metadataXml', e.target.value)}
            />
          </Field>
          <fieldset disabled={saving}>
            <legend className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">Email address comes from</legend>
            <div className="flex flex-wrap gap-4">
              {(
                [
                  ['nameid', 'The NameID'],
                  ['attribute', 'An attribute'],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                  <input
                    type="radio"
                    name={`${ids}-email-source`}
                    value={value}
                    checked={draft.emailSource === value}
                    onChange={() => set('emailSource', value)}
                    className="accent-indigo-600"
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          {draft.emailSource === 'attribute' && (
            <Field id={`${ids}-email-attribute`} label="Email attribute name">
              <input
                id={`${ids}-email-attribute`}
                className={`${INPUT_CLASSES} font-mono`}
                value={draft.emailAttribute}
                required
                placeholder="email"
                onChange={(e) => set('emailAttribute', e.target.value)}
              />
            </Field>
          )}
          <Field
            id={`${ids}-sp-key`}
            label="SP signing key (optional)"
            hint="A PEM private key, only if your IdP requires signed sign-in requests. Stored encrypted."
          >
            <textarea
              id={`${ids}-sp-key`}
              rows={3}
              spellCheck={false}
              autoComplete="off"
              className={`${INPUT_CLASSES} font-mono`}
              value={draft.spPrivateKey}
              onChange={(e) => set('spPrivateKey', e.target.value)}
            />
          </Field>
        </>
      )}

      {error && <ErrorNote message={error} />}

      <div className="flex justify-end gap-2">
        <button type="button" className={SECONDARY_BUTTON_CLASSES} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="submit" className={PRIMARY_BUTTON_CLASSES} disabled={saving} data-testid="sso-add-submit">
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Add provider
        </button>
      </div>
    </form>
  );
}

/** One provider: its status, the values for the IdP, its domains and its actions. */
function ProviderRow({
  view,
  onChange,
  onRemoved,
}: {
  view: AdminSsoProviderView;
  onChange: (view: AdminSsoProviderView) => void;
  onRemoved: (id: string) => void;
}) {
  const ids = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [domain, setDomain] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);
  const origin = typeof window === 'undefined' ? '' : window.location.origin;

  const run = async (path: string, init: { method: string; body?: unknown }, fallback: string) => {
    setBusy(true);
    setError(null);
    const result = await call(path, init);
    setBusy(false);
    if (!result.ok) {
      setError(ssoAdminErrorMessage(result.status, result.body, fallback));
      return null;
    }
    return result.body as AdminSsoProviderView;
  };

  const base = `/${view.id}`;
  const verifiedCount = view.domains.filter((d) => d.verified).length;

  return (
    <li className="flex flex-col gap-3 py-4" data-testid={`sso-provider-${view.slug}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{view.display_name}</span>
        <span className={NEUTRAL_CHIP_CLASSES}>{view.protocol === 'oidc' ? 'OIDC' : 'SAML 2.0'}</span>
        {view.routable ? (
          <span className={LIVE_CHIP_CLASSES}>Live</span>
        ) : view.enabled ? (
          <span className={WAITING_CHIP_CLASSES}>Needs a verified domain</span>
        ) : (
          <span className={NEUTRAL_CHIP_CLASSES}>Disabled</span>
        )}
        <span className="ml-auto font-mono text-xs text-slate-500 dark:text-slate-400">{view.identity_kind}</span>
      </div>
      <p className="text-xs text-slate-600 dark:text-slate-400">
        {view.tenant_name ? `Workspace: ${view.tenant_name}. ` : ''}
        Issuer: <span className="font-mono">{view.issuer}</span>
      </p>

      <dl className="grid gap-1 rounded-md bg-slate-50 p-3 text-xs dark:bg-slate-950">
        {ssoSetupDetails(origin, view).map((detail) => (
          <div key={detail.label} className="flex flex-col sm:flex-row sm:gap-2">
            <dt className="shrink-0 font-medium text-slate-700 dark:text-slate-300 sm:w-44">{detail.label}</dt>
            <dd className="break-all font-mono text-slate-600 dark:text-slate-400">{detail.value}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-slate-700 dark:text-slate-200">
          Domains <span className="font-normal text-slate-500">({verifiedCount} verified)</span>
        </h4>
        {view.domains.length > 0 && (
          <ul className="flex flex-col gap-1">
            {view.domains.map((d) => (
              <li key={d.domain} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-mono text-slate-800 dark:text-slate-200">{d.domain}</span>
                {d.verified ? (
                  <span className={LIVE_CHIP_CLASSES}>Verified</span>
                ) : (
                  <button
                    type="button"
                    className={SECONDARY_BUTTON_CLASSES}
                    disabled={busy}
                    onClick={async () => {
                      const next = await run(`${base}/domains/${encodeURIComponent(d.domain)}/verify`, { method: 'POST' }, 'The domain could not be verified.');
                      if (next) onChange(next);
                    }}
                  >
                    Mark verified
                  </button>
                )}
                <button
                  type="button"
                  className={`${SECONDARY_BUTTON_CLASSES} ml-auto`}
                  disabled={busy}
                  aria-label={`Remove ${d.domain}`}
                  onClick={async () => {
                    const next = await run(`${base}/domains/${encodeURIComponent(d.domain)}`, { method: 'DELETE' }, 'The domain could not be removed.');
                    if (next) onChange(next);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex items-center gap-2"
          onSubmit={async (event) => {
            event.preventDefault();
            const next = await run(`${base}/domains`, { method: 'POST', body: { domain } }, 'The domain could not be added.');
            if (next) {
              onChange(next);
              setDomain('');
            }
          }}
        >
          <label htmlFor={`${ids}-domain`} className="sr-only">
            Add a domain to {view.display_name}
          </label>
          <input
            id={`${ids}-domain`}
            className={`${INPUT_CLASSES} font-mono`}
            value={domain}
            placeholder="acme.com"
            onChange={(e) => setDomain(e.target.value)}
            disabled={busy}
          />
          <button
            type="submit"
            className={`${SECONDARY_BUTTON_CLASSES} shrink-0 whitespace-nowrap`}
            disabled={busy || domain.trim() === ''}
          >
            <Plus className="h-3.5 w-3.5" /> Add domain
          </button>
        </form>
      </div>

      {error && <ErrorNote message={error} />}

      <div className="flex flex-wrap justify-end gap-2">
        {confirmRemove ? (
          <>
            <button type="button" className={SECONDARY_BUTTON_CLASSES} onClick={() => setConfirmRemove(false)} disabled={busy}>
              Keep it
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_CLASSES}
              disabled={busy}
              onClick={async () => {
                const removed = await run(base, { method: 'DELETE' }, 'The identity provider could not be removed.');
                if (removed) onRemoved(view.id);
              }}
            >
              Remove {view.display_name}
            </button>
          </>
        ) : (
          <button type="button" className={SECONDARY_BUTTON_CLASSES} onClick={() => setConfirmRemove(true)} disabled={busy}>
            Remove…
          </button>
        )}
        <button
          type="button"
          className={view.enabled ? SECONDARY_BUTTON_CLASSES : PRIMARY_BUTTON_CLASSES}
          disabled={busy}
          onClick={async () => {
            const next = await run(base, { method: 'PATCH', body: { enabled: !view.enabled } }, 'The identity provider could not be updated.');
            if (next) onChange(next);
          }}
        >
          {view.enabled ? 'Disable' : 'Enable'}
        </button>
      </div>
    </li>
  );
}

/** The Single sign-on card. */
export default function SsoProvidersCard() {
  const [providers, setProviders] = useState<AdminSsoProviderView[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  // Fetch and adopt the list. Every state update happens after the request, so the mount effect
  // below never sets state synchronously; Retry resets the loading state first (`load`).
  const fetchProviders = useCallback(async () => {
    try {
      const response = await fetch(SSO_PROVIDERS_URL, { cache: 'no-store' });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        setLoadError(ssoAdminErrorMessage(response.status, body, 'Single sign-on providers could not be loaded.'));
        return;
      }
        setLoadError(null);
      // Keep only well-formed rows: a malformed answer must not take the settings page down.
      const listed = (body as { providers?: unknown } | null)?.providers;
      setProviders(Array.isArray(listed) ? listed.filter(isProviderView) : []);
    } catch {
      setLoadError('Single sign-on providers could not be loaded. Check the configuration service and retry.');
    } finally {
      setLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    await fetchProviders();
  }, [fetchProviders]);

  useEffect(() => {
    void fetchProviders();
  }, [fetchProviders]);

  const replace = (view: AdminSsoProviderView) =>
    setProviders((current) => (current ?? []).map((p) => (p.id === view.id ? view : p)));

  return (
    <section
      aria-label="Single sign-on"
      className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
      data-testid="sso-providers-card"
    >
      <div className="flex items-center gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800">
          <Building2 size={ICON_SIZE.dense} className="text-slate-600 dark:text-slate-300" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Single sign-on</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            A workspace’s own SAML 2.0 or OIDC identity provider, for the email domains it owns.
          </p>
        </div>
        {!adding && (
          <button type="button" className={SECONDARY_BUTTON_CLASSES} onClick={() => setAdding(true)} disabled={loading || !!loadError}>
            <Plus className="h-3.5 w-3.5" /> Add identity provider
          </button>
        )}
      </div>

      <div className="flex flex-col gap-4 px-5 py-4">
        {adding && (
          <AddProviderForm
            onCancel={() => setAdding(false)}
            onAdded={(view) => {
              setProviders((current) => [view, ...(current ?? [])]);
              setAdding(false);
            }}
          />
        )}

        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading single sign-on providers…
          </div>
        )}

        {!loading && loadError && (
          <div>
            <ErrorNote message={loadError} />
            <button type="button" onClick={() => void load()} className={`${SECONDARY_BUTTON_CLASSES} mt-3`}>
              <RefreshCw className="h-3.5 w-3.5" /> Retry
            </button>
          </div>
        )}

        {!loading && !loadError && providers && providers.length === 0 && !adding && (
          <p className="text-sm text-slate-600 dark:text-slate-400">
            No identity providers yet. Add one, give it the email domains it owns, mark them verified and enable it.
          </p>
        )}

        {!loading && !loadError && providers && providers.length > 0 && (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {providers.map((view) => (
              <ProviderRow
                key={view.id}
                view={view}
                onChange={replace}
                onRemoved={(id) => setProviders((current) => (current ?? []).filter((p) => p.id !== id))}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

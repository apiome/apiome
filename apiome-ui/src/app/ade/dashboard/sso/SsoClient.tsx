'use client';

/**
 * Workspace → Single sign-on — `/ade/dashboard/sso` (EID-1.2, #5012).
 *
 * Where a workspace's owners connect their own identity provider (SAML 2.0 or OIDC):
 *
 * - the **provider list** — name, protocol, how many of its domains are verified, how many members
 *   signed in through it, and whether sign-ins reach it (Live, Needs a verified domain, Disabled);
 * - **Add provider** — the registration dialog;
 * - a provider's name opens its drawer: **Configure** (the values for the IdP and the connection's
 *   settings) and **Domains** (add a domain, publish its DNS TXT challenge, **Verify**), with
 *   **Enable** / **Disable** and **Remove** in the footer.
 *
 * Sign-ins reach a provider only while it is enabled *and* has a verified domain. Owners and
 * tenant admins only: REST enforces it, and this page says so to everyone else instead of
 * showing an error.
 */

import * as React from 'react';
import { KeyRound, Plus, RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Badge, Button, EmptyState, GatedState } from '@/app/components/ui';
import { fetchMyPermissions, fetchRoles, type RoleRecord } from '@/app/components/ade/access/accessApi';
import {
  fetchSsoProviders,
  SsoAddProviderDialog,
  SsoProviderDrawer,
  type SsoDrawerTab,
} from '@/app/components/ade/sso';
import { useAuthSession } from '@lib/auth/session-client';
import {
  ssoDomainSummary,
  ssoProtocolLabel,
  ssoProviderStatus,
  type SsoDomainCheck,
  type WorkspaceSsoProvider,
} from '@lib/workspace-sso';

const HOME_ROUTE = '/ade/dashboard';

/** Props for {@link SsoClient} — all optional, for tests and the docs fixtures. */
export interface SsoClientProps {
  /** Open this provider's drawer once the list has loaded. */
  initialOpenId?: string;
  /** The drawer tab to open on. */
  initialTab?: SsoDrawerTab;
  /** DNS checks the drawer shows from the start. */
  initialChecks?: Readonly<Record<string, SsoDomainCheck>>;
  /** Open with the Add provider dialog showing. */
  initialAdding?: boolean;
}

/**
 * The Single sign-on page.
 *
 * @param props See {@link SsoClientProps}.
 * @returns The page.
 */
export default function SsoClient({
  initialOpenId,
  initialTab,
  initialChecks,
  initialAdding = false,
}: SsoClientProps = {}) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [providers, setProviders] = React.useState<WorkspaceSsoProvider[] | null>(null);
  const [roles, setRoles] = React.useState<RoleRecord[]>([]);
  // null while unknown; false sends the reader to the "owners and admins" state.
  const [isAdmin, setIsAdmin] = React.useState<boolean | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [openId, setOpenId] = React.useState<string | null>(initialOpenId ?? null);
  const [adding, setAdding] = React.useState(initialAdding);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      const me = await fetchMyPermissions();
      const admin = Boolean(me?.is_admin);
      setIsAdmin(admin);
      if (!admin) return;
      setProviders(await fetchSsoProviders());
      // The role list only feeds a select: without it the choice falls back to the default.
      fetchRoles().then(setRoles).catch(() => setRoles([]));
    } catch (caught) {
      setProviders(null);
      setError(caught instanceof Error ? caught.message : 'Could not load single sign-on');
    }
  }, []);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  const replace = (next: WorkspaceSsoProvider) =>
    setProviders((current) => (current ?? []).map((provider) => (provider.id === next.id ? next : provider)));

  const open = providers?.find((provider) => provider.id === openId) ?? null;
  const canAdd = Boolean(tenantId) && isAdmin === true && !error;

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Workspace' }, { label: 'Single sign-on' }]}
        title="Single sign-on"
        description="Let people in your email domains sign in through your own identity provider."
        primaryAction={
          canAdd ? (
            <Button onClick={() => setAdding(true)} data-testid="sso-add">
              <Plus aria-hidden />
              Add provider
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Single sign-on belongs to one workspace." />
        ) : error ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="Single sign-on could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : isAdmin === false ? (
          <GatedState
            title="Owners and admins only"
            description="Ask a workspace owner or admin to set up single sign-on."
            data-testid="sso-not-admin"
          />
        ) : providers === null ? (
          <p className="wsso-note" data-testid="sso-loading">
            Reading your identity providers…
          </p>
        ) : providers.length === 0 ? (
          <EmptyState
            variant="compact"
            surface={false}
            icon={<KeyRound aria-hidden />}
            title="No identity providers yet"
            description="Add your SAML 2.0 or OIDC provider, verify a domain, then enable it."
            action={
              <Button onClick={() => setAdding(true)}>
                <Plus aria-hidden />
                Add provider
              </Button>
            }
          />
        ) : (
          <div className="tm-table-wrap">
            <table className="tm-table" data-testid="sso-table">
              <caption className="sr-only">Identity providers of this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Provider</th>
                  <th scope="col">Protocol</th>
                  <th scope="col">Domains</th>
                  <th scope="col">Members</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((provider) => {
                  const status = ssoProviderStatus(provider);
                  return (
                    <tr key={provider.id} data-testid={`sso-row-${provider.slug}`}>
                      <td>
                        <button type="button" className="wsso-name" onClick={() => setOpenId(provider.id)}>
                          {provider.display_name}
                        </button>
                        <span className="tm-slug mono">{provider.slug}</span>
                      </td>
                      <td>{ssoProtocolLabel(provider.protocol)}</td>
                      <td>
                        <span className="wsso-domains-cell">
                          {provider.domains.map((domain) => (
                            <span key={domain.domain} className="mono">
                              {domain.domain}
                            </span>
                          ))}
                          <span className="tm-muted">{ssoDomainSummary(provider.domains)}</span>
                        </span>
                      </td>
                      <td className="tm-num">{provider.member_count}</td>
                      <td>
                        <Badge variant={status.tone} dot data-status-kind={status.kind}>
                          {status.label}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </PageBody>

      <SsoAddProviderDialog
        open={adding}
        onOpenChange={setAdding}
        roles={roles}
        onAdded={(provider) => {
          setProviders((current) => [provider, ...(current ?? [])]);
          // Straight to the next step: the new provider needs a domain before it can route.
          setOpenId(provider.id);
        }}
      />
      <SsoProviderDrawer
        provider={open}
        onOpenChange={(next) => {
          if (!next) setOpenId(null);
        }}
        roles={roles}
        onChange={replace}
        onRemoved={(id) => {
          setProviders((current) => (current ?? []).filter((provider) => provider.id !== id));
          setOpenId(null);
        }}
        initialTab={initialTab}
        initialChecks={initialChecks}
      />
    </Page>
  );
}

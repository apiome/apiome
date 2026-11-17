'use client';

import * as React from 'react';

import {
  Alert,
  Badge,
  Button,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  FormField,
  Input,
  Tabs,
  TabsContent,
  TabsCount,
  TabsList,
  TabsTrigger,
} from '@/app/components/ui';
import type { RoleRecord } from '@/app/components/ade/access/accessApi';
import {
  buildWorkspaceSsoUpdatePayload,
  SSO_BUSY_REASON,
  ssoProtocolLabel,
  ssoProviderStatus,
  ssoRemoveImpact,
  ssoSetupDetails,
  workspaceSsoEditFrom,
  type SsoDomainCheck,
  type WorkspaceSsoEdit,
  type WorkspaceSsoProvider,
} from '@lib/workspace-sso';
import { SsoConnectionFields } from './SsoConnectionFields';
import { SsoCopyValue } from './SsoCopyValue';
import { SsoDomainsPanel } from './SsoDomainsPanel';
import { removeSsoProvider, updateSsoProvider } from './workspaceSsoApi';

/** The drawer's tabs. */
export type SsoDrawerTab = 'configure' | 'domains';

/** Props for {@link SsoProviderDrawer}. */
export interface SsoProviderDrawerProps {
  /** The provider shown, or null when the drawer is closed. */
  provider: WorkspaceSsoProvider | null;
  onOpenChange: (open: boolean) => void;
  /** The workspace's roles, for the default-role choice. */
  roles: readonly RoleRecord[];
  /** Told whenever the provider changed. */
  onChange: (provider: WorkspaceSsoProvider) => void;
  /** Told when the provider was removed. */
  onRemoved: (id: string) => void;
  /** The tab to open on (defaults to Configure). */
  initialTab?: SsoDrawerTab;
  /** DNS checks to show from the start (stories, fixtures); normally empty. */
  initialChecks?: Readonly<Record<string, SsoDomainCheck>>;
  /** Open with the Remove confirmation showing (fixtures); normally false. */
  initialConfirmRemove?: boolean;
}

/**
 * One identity provider, in a drawer (EID-1.2, #5012).
 *
 * - **Configure** — the values to give the IdP (redirect URI, or ACS URL and SP entity ID), the
 *   connection's settings, and **Save changes**. Secrets are never read back: a blank secret keeps
 *   the stored one.
 * - **Domains** — the email domains it signs in, each with its DNS challenge and **Verify**.
 *
 * The footer holds **Enable** / **Disable** — disabling stops sign-ins reaching the IdP at once —
 * and **Remove**, which first says how many members signed in through the provider.
 *
 * @param props See {@link SsoProviderDrawerProps}.
 * @returns The drawer.
 */
export function SsoProviderDrawer({
  provider,
  onOpenChange,
  roles,
  onChange,
  onRemoved,
  initialTab = 'configure',
  initialChecks,
  initialConfirmRemove = false,
}: SsoProviderDrawerProps) {
  const [tab, setTab] = React.useState<string>(initialTab);
  const [edit, setEdit] = React.useState<WorkspaceSsoEdit | null>(provider ? workspaceSsoEditFrom(provider) : null);
  const [checks, setChecks] = React.useState<Record<string, SsoDomainCheck>>({ ...(initialChecks ?? {}) });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);
  const [confirmRemove, setConfirmRemove] = React.useState(initialConfirmRemove);
  const origin = typeof window === 'undefined' ? '' : window.location.origin;

  // A different provider (or the same one reopened) starts the drawer over; an update to the
  // provider on screen — a verified domain, a save — must not throw the reader's edits away.
  const shownId = provider?.id ?? null;
  const shownRef = React.useRef<string | null>(shownId);
  React.useEffect(() => {
    if (shownRef.current === shownId) return;
    shownRef.current = shownId;
    setTab(initialTab);
    setEdit(provider ? workspaceSsoEditFrom(provider) : null);
    setChecks({ ...(initialChecks ?? {}) });
    setError(null);
    setSaved(false);
    setConfirmRemove(initialConfirmRemove);
  }, [shownId, provider, initialTab, initialChecks, initialConfirmRemove]);

  if (!provider || !edit) {
    return null;
  }

  const status = ssoProviderStatus(provider);
  const changes = buildWorkspaceSsoUpdatePayload(provider, edit);
  const dirty = Object.keys(changes).length > 0;
  const verifiedCount = provider.domains.filter((domain) => domain.verified).length;

  /** Run one provider-level request, showing a refusal's message. */
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The request failed.');
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      const next = await updateSsoProvider(provider.id, changes);
      onChange(next);
      setEdit(workspaceSsoEditFrom(next));
      setSaved(true);
    });

  const toggle = () => run(async () => onChange(await updateSsoProvider(provider.id, { enabled: !provider.enabled })));

  const remove = () =>
    run(async () => {
      await removeSsoProvider(provider.id);
      onRemoved(provider.id);
    });

  return (
    <Drawer open onOpenChange={(next) => !busy && onOpenChange(next)}>
      {/* The sub-line is badges, not a `DrawerDescription`, so the description reference Radix
          adds is cleared rather than left dangling (HIVE-2.2's rule). */}
      <DrawerContent size="lg" data-testid="sso-provider-drawer" aria-describedby={undefined}>
        <DrawerHeader>
          <DrawerTitle className="truncate">{provider.display_name}</DrawerTitle>
          <div className="wsso-drawer__meta">
            <Badge variant="outline">{ssoProtocolLabel(provider.protocol)}</Badge>
            <Badge variant={status.tone} dot data-testid="sso-drawer-status">
              {status.label}
            </Badge>
            <span className="mono">{provider.identity_kind}</span>
          </div>
        </DrawerHeader>

        <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <TabsList className="shrink-0 px-5">
            <TabsTrigger value="configure" size="sm">
              Configure
            </TabsTrigger>
            <TabsTrigger value="domains" size="sm">
              Domains
              <TabsCount>{provider.domains.length}</TabsCount>
            </TabsTrigger>
          </TabsList>

          <DrawerBody className="min-h-0 flex-1 overflow-y-auto">
            {error ? (
              <Alert variant="error" className="mb-4" data-testid="sso-drawer-error">
                {error}
              </Alert>
            ) : null}

            <TabsContent value="configure">
              <form
                id="wsso-configure-form"
                className="wsso-form"
                data-testid="sso-configure-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!busy && dirty) void save();
                }}
              >
                <section className="wsso-section" aria-labelledby="wsso-setup-title">
                  <h3 id="wsso-setup-title" className="wsso-section__title">
                    Give these to your identity provider
                  </h3>
                  <dl className="wsso-record">
                    {ssoSetupDetails(origin, provider).map((detail) => (
                      <div key={detail.label} className="wsso-record__row">
                        <dt>{detail.label}</dt>
                        <dd>
                          <SsoCopyValue label={detail.label} value={detail.value} />
                        </dd>
                      </div>
                    ))}
                    <div className="wsso-record__row">
                      <dt>{provider.protocol === 'oidc' ? 'Issuer' : 'IdP entity ID'}</dt>
                      <dd className="mono wsso-break">{provider.issuer}</dd>
                    </div>
                  </dl>
                </section>

                <FormField label="Name" htmlFor="wsso-edit-name" required>
                  <Input
                    id="wsso-edit-name"
                    value={edit.displayName}
                    required
                    disabled={busy}
                    onChange={(event) => {
                      setSaved(false);
                      setEdit({ ...edit, displayName: event.target.value });
                    }}
                  />
                </FormField>

                <SsoConnectionFields
                  idPrefix="wsso-edit"
                  protocol={provider.protocol}
                  mode="edit"
                  values={edit}
                  onChange={(key, value) => {
                    setSaved(false);
                    setEdit({ ...edit, [key]: value });
                  }}
                  roles={roles}
                  disabled={busy}
                  stored={{ clientSecret: provider.has_client_secret, spPrivateKey: provider.has_sp_private_key }}
                />

                <div className="wsso-save">
                  <Button
                    type="submit"
                    disabled={busy || !dirty}
                    title={busy ? SSO_BUSY_REASON : dirty ? undefined : 'Nothing has changed'}
                    data-testid="sso-configure-save"
                  >
                    {busy ? 'Saving…' : 'Save changes'}
                  </Button>
                  {saved ? (
                    <span className="wsso-note" role="status">
                      Saved.
                    </span>
                  ) : null}
                </div>
              </form>
            </TabsContent>

            <TabsContent value="domains">
              <SsoDomainsPanel
                provider={provider}
                onChange={onChange}
                checks={checks}
                onCheck={(domain, check) => setChecks((current) => ({ ...current, [domain]: check }))}
              />
            </TabsContent>
          </DrawerBody>
        </Tabs>

        <DrawerFooter className="wsso-drawer__footer">
          {confirmRemove ? (
            <div className="wsso-confirm" role="group" aria-label={`Remove ${provider.display_name}`}>
              <p className="wsso-confirm__text" data-testid="sso-remove-impact">
                {ssoRemoveImpact(provider.member_count)}
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirmRemove(false)}
                disabled={busy}
                title={busy ? SSO_BUSY_REASON : undefined}
              >
                Keep it
              </Button>
              <Button
                type="button"
                variant="danger"
                onClick={() => void remove()}
                disabled={busy}
                title={busy ? SSO_BUSY_REASON : undefined}
                data-testid="sso-remove-confirm"
              >
                Remove {provider.display_name}
              </Button>
            </div>
          ) : (
            <>
              <Button
                type="button"
                variant="danger-soft"
                onClick={() => setConfirmRemove(true)}
                disabled={busy}
                title={busy ? SSO_BUSY_REASON : undefined}
                data-testid="sso-remove"
              >
                Remove…
              </Button>
              <span className="wsso-drawer__status">
                {provider.enabled && verifiedCount === 0 ? 'Verify a domain to start routing sign-ins.' : null}
              </span>
              <Button
                type="button"
                variant={provider.enabled ? 'outline' : 'primary'}
                onClick={() => void toggle()}
                disabled={busy}
                title={busy ? SSO_BUSY_REASON : undefined}
                data-testid="sso-toggle"
              >
                {provider.enabled ? 'Disable' : 'Enable'}
              </Button>
            </>
          )}
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  );
}

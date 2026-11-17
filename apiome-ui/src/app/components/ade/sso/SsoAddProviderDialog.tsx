'use client';

import * as React from 'react';
import { KeyRound } from 'lucide-react';

import {
  Alert,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
  RadioGroup,
  RadioGroupItem,
} from '@/app/components/ui';
import type { RoleRecord } from '@/app/components/ade/access/accessApi';
import {
  buildWorkspaceSsoCreatePayload,
  EMPTY_WORKSPACE_SSO_DRAFT,
  SSO_BUSY_REASON,
  suggestSsoSlug,
  type WorkspaceSsoDraft,
  type WorkspaceSsoProvider,
} from '@lib/workspace-sso';
import { SsoConnectionFields } from './SsoConnectionFields';
import { createSsoProvider } from './workspaceSsoApi';

const FORM_ID = 'wsso-add-form';

/** Props for {@link SsoAddProviderDialog}. */
export interface SsoAddProviderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The workspace's roles, for the default-role choice. */
  roles: readonly RoleRecord[];
  /** Told when a provider was registered, with the provider as REST returned it. */
  onAdded: (provider: WorkspaceSsoProvider) => void;
}

/**
 * **Add provider** — register the workspace's identity provider (EID-1.2, #5012).
 *
 * OIDC by issuer (the discovery document is read and checked server-side) or SAML 2.0 by metadata
 * URL or pasted XML. Secrets are write-only. The provider is created disabled: it routes no
 * sign-in until a domain is verified and the provider is enabled. A refusal's message is REST's,
 * shown as is.
 *
 * @param props See {@link SsoAddProviderDialogProps}.
 * @returns The dialog.
 */
export function SsoAddProviderDialog({ open, onOpenChange, roles, onAdded }: SsoAddProviderDialogProps) {
  const [draft, setDraft] = React.useState<WorkspaceSsoDraft>(EMPTY_WORKSPACE_SSO_DRAFT);
  const [slugEdited, setSlugEdited] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setDraft(EMPTY_WORKSPACE_SSO_DRAFT);
    setSlugEdited(false);
    setBusy(false);
    setError(null);
  }, [open]);

  const set = <K extends keyof WorkspaceSsoDraft>(key: K, value: WorkspaceSsoDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const provider = await createSsoProvider(buildWorkspaceSsoCreatePayload(draft));
      onAdded(provider);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The identity provider could not be added.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="sso-add-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="tnt-icon-tile" data-tone="accent">
              <KeyRound aria-hidden />
            </span>
            Add provider
          </DialogTitle>
          <DialogDescription>
            Connect your identity provider. It stays off until you verify a domain and enable it.
          </DialogDescription>
        </DialogHeader>

        <form
          id={FORM_ID}
          className="wsso-form wsso-form--dialog"
          data-testid="sso-add-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy) void submit();
          }}
        >
          {error ? <Alert variant="error">{error}</Alert> : null}

          <fieldset className="wsso-fieldset" disabled={busy}>
            <legend className="wsso-legend">Protocol</legend>
            <RadioGroup
              className="wsso-radios"
              value={draft.protocol}
              onValueChange={(next) => set('protocol', next === 'saml' ? 'saml' : 'oidc')}
            >
              <RadioGroupItem name="wsso-add-protocol" value="oidc" label="OIDC" />
              <RadioGroupItem name="wsso-add-protocol" value="saml" label="SAML 2.0" />
            </RadioGroup>
          </fieldset>

          <div className="wsso-grid">
            <FormField label="Name" htmlFor="wsso-add-name" required>
              <Input
                id="wsso-add-name"
                value={draft.displayName}
                required
                disabled={busy}
                placeholder="Acme Okta"
                autoFocus
                onChange={(event) => {
                  const name = event.target.value;
                  setDraft((current) => ({
                    ...current,
                    displayName: name,
                    slug: slugEdited ? current.slug : suggestSsoSlug(name),
                  }));
                }}
              />
            </FormField>
            <FormField
              label="ID"
              htmlFor="wsso-add-slug"
              required
              helperText="Lower-case letters, digits and hyphens. Appears in sign-in URLs."
            >
              <Input
                id="wsso-add-slug"
                className="mono"
                value={draft.slug}
                required
                maxLength={28}
                disabled={busy}
                placeholder="acme-okta"
                onChange={(event) => {
                  setSlugEdited(true);
                  set('slug', event.target.value);
                }}
              />
            </FormField>
          </div>

          {draft.protocol === 'oidc' ? (
            <FormField
              label="Issuer URL"
              htmlFor="wsso-add-issuer"
              required
              helperText="Apiome reads /.well-known/openid-configuration from it."
            >
              <Input
                id="wsso-add-issuer"
                type="url"
                value={draft.issuer}
                required
                disabled={busy}
                placeholder="https://acme.okta.com"
                onChange={(event) => set('issuer', event.target.value)}
              />
            </FormField>
          ) : null}

          <SsoConnectionFields
            idPrefix="wsso-add"
            protocol={draft.protocol}
            mode="create"
            values={draft}
            onChange={(key, value) => set(key as keyof WorkspaceSsoDraft, value as never)}
            roles={roles}
            disabled={busy}
          />
        </form>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={busy}
            title={busy ? SSO_BUSY_REASON : undefined}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form={FORM_ID}
            disabled={busy}
            title={busy ? SSO_BUSY_REASON : undefined}
            data-testid="sso-add-submit"
          >
            {busy ? 'Adding…' : 'Add provider'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

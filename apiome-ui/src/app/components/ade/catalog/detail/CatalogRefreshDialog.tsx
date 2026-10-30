'use client';

/**
 * Set up or edit a catalog item's live refresh — MFI-31.1 (#4398).
 *
 * Opened from the **Live refresh** card's **Set up refresh…** / **Edit refresh…** button. The user
 * picks how to discover the source (GraphQL introspection, gRPC server reflection or a FHIR server's
 * `/metadata`), the endpoint,
 * the cadence and an optional credential. An existing credential is never shown: the credential
 * select starts on **Keep current credential**, and a new one replaces it. Saving sends
 * `PUT /api/catalog/{id}/refresh`; anything REST refuses (an unsafe URL, a malformed credential) is
 * shown under the form.
 */

import * as React from 'react';

import { Button } from '@/app/components/ui/Button';
import { Checkbox } from '@/app/components/ui/Checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/app/components/ui/Select';
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';

import {
  REFRESH_AUTH_OPTIONS,
  REFRESH_CADENCE_OPTIONS,
  REFRESH_KEEP_VERSIONS_MAX,
  refreshAdapterLabel,
  refreshEndpointHint,
  refreshFormError,
  refreshFormFrom,
  refreshPayload,
  type CatalogRefresh,
  type RefreshForm,
} from './catalogRefreshModel';

export interface CatalogRefreshDialogProps {
  /** Whether the dialog is showing. Mount it with a fresh `key` per open so the form resets. */
  open: boolean;
  /** The item's id and name. */
  item: { id: string; name: string };
  /** The item's current refresh answer (null while it loads). */
  refresh: CatalogRefresh | null;
  /** Called with the open state. */
  onOpenChange: (open: boolean) => void;
  /** Called with REST's answer after a successful save. */
  onSaved: (refresh: CatalogRefresh) => void;
}

const FIELD = {
  adapter: 'catalog-refresh-adapter',
  endpoint: 'catalog-refresh-endpoint',
  cadence: 'catalog-refresh-cadence',
  keep: 'catalog-refresh-keep-versions',
  secure: 'catalog-refresh-secure',
  auth: 'catalog-refresh-auth',
  header: 'catalog-refresh-header-name',
  secret: 'catalog-refresh-secret',
} as const;

/**
 * Render the dialog. See {@link CatalogRefreshDialogProps}.
 *
 * @returns The dialog.
 */
export function CatalogRefreshDialog({ open, item, refresh, onOpenChange, onSaved }: CatalogRefreshDialogProps) {
  const [form, setForm] = React.useState<RefreshForm>(() => refreshFormFrom(refresh));
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const returnFocus = useReturnFocus(open);

  const adapters = refresh?.adapters?.length ? refresh.adapters : ['graphql', 'grpc'];
  const endpointHint = refreshEndpointHint(form.adapter);
  const update = (patch: Partial<RefreshForm>) => {
    setForm((current) => ({ ...current, ...patch }));
    setError(null);
  };

  const handleSave = async () => {
    const problem = refreshFormError(form);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    try {
      const response = await fetch(`/api/catalog/${encodeURIComponent(item.id)}/refresh`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(refreshPayload(form)),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.success === false) {
        throw new Error(data?.error || 'The refresh setting could not be saved.');
      }
      onSaved(data as CatalogRefresh);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The refresh setting could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const needsSecret = form.authType === 'bearer' || form.authType === 'oauth2' || form.authType === 'header';

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : undefined)}>
      <DialogContent size="sm" onCloseAutoFocus={returnFocus} data-testid="catalog-refresh-dialog">
        <DialogHeader>
          <DialogTitle>Live refresh for {item.name}</DialogTitle>
          <DialogDescription>
            Apiome re-discovers the live source on this cadence and adds a version when it changed. A failed
            check is shown on the card and never changes the item.
          </DialogDescription>
        </DialogHeader>

        <div className="cid-refresh-form">
          <FormField label="Discover with" htmlFor={FIELD.adapter}>
            <Select value={form.adapter} onValueChange={(adapter) => update({ adapter })}>
              <SelectTrigger id={FIELD.adapter} data-testid="catalog-refresh-adapter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {adapters.map((adapter) => (
                  <SelectItem key={adapter} value={adapter}>
                    {refreshAdapterLabel(adapter)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>

          <FormField label="Endpoint" htmlFor={FIELD.endpoint} helperText={endpointHint.hint}>
            <Input
              id={FIELD.endpoint}
              className="mono"
              value={form.endpoint}
              placeholder={endpointHint.placeholder}
              onChange={(event) => update({ endpoint: event.target.value })}
              data-testid="catalog-refresh-endpoint"
            />
          </FormField>

          {form.adapter === 'grpc' ? (
            <label className="cid-refresh-form__check" htmlFor={FIELD.secure}>
              <Checkbox
                id={FIELD.secure}
                checked={form.secure}
                onCheckedChange={(checked) => update({ secure: checked === true })}
                data-testid="catalog-refresh-secure"
              />
              Use TLS
            </label>
          ) : null}

          <FormField label="Cadence" htmlFor={FIELD.cadence}>
            <Select value={form.cadence} onValueChange={(cadence) => update({ cadence: cadence as RefreshForm['cadence'] })}>
              <SelectTrigger id={FIELD.cadence} data-testid="catalog-refresh-cadence">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {REFRESH_CADENCE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>

          <FormField
            label="Keep versions"
            htmlFor={FIELD.keep}
            helperText="Keeps the newest versions refresh adds; older ones are pruned. Tagged, breaking and converted versions are always kept."
          >
            <Input
              id={FIELD.keep}
              type="number"
              inputMode="numeric"
              min={1}
              max={REFRESH_KEEP_VERSIONS_MAX}
              value={form.keepVersions}
              onChange={(event) => update({ keepVersions: event.target.value })}
              data-testid="catalog-refresh-keep-versions"
            />
          </FormField>

          <FormField label="Credential" htmlFor={FIELD.auth}>
            <Select
              value={form.authType}
              onValueChange={(authType) => update({ authType: authType as RefreshForm['authType'], secret: '' })}
            >
              <SelectTrigger id={FIELD.auth} data-testid="catalog-refresh-auth">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {refresh?.hasCredential ? <SelectItem value="keep">Keep current credential</SelectItem> : null}
                {REFRESH_AUTH_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>

          {form.authType === 'header' ? (
            <FormField label="Header name" htmlFor={FIELD.header}>
              <Input
                id={FIELD.header}
                className="mono"
                value={form.headerName}
                placeholder="X-Api-Key"
                onChange={(event) => update({ headerName: event.target.value })}
                data-testid="catalog-refresh-header-name"
              />
            </FormField>
          ) : null}

          {needsSecret ? (
            <FormField
              label={form.authType === 'header' ? 'Header value' : 'Token'}
              htmlFor={FIELD.secret}
              helperText="Stored encrypted. It is never shown again."
            >
              <Input
                id={FIELD.secret}
                type="password"
                autoComplete="off"
                value={form.secret}
                onChange={(event) => update({ secret: event.target.value })}
                data-testid="catalog-refresh-secret"
              />
            </FormField>
          ) : null}

          {error ? (
            <div className="cid-refresh__error" role="alert" data-testid="catalog-refresh-error">
              {error}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={saving}
            title={saving ? 'Wait for the save to finish' : undefined}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={saving}
            title={saving ? 'Saving the refresh setting' : undefined}
            onClick={() => void handleSave()}
            data-testid="catalog-refresh-save"
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

'use client';

/**
 * CatalogDriftAlertsDialog (MFI-31.3, #4400) — the workspace's catalog drift alert settings.
 *
 * Opened from the Catalog page's **Drift alerts** button. It decides who hears about drift a
 * scheduled live refresh finds, and when:
 *
 * - **Announce** — breaking, dangerous and safe drift each on or off. Drift that is not announced
 *   still shows its badge (by default safe drift only badges).
 * - **Delivery** — right away, or one daily digest; with the digest, breaking drift can still go
 *   out right away.
 * - **Email** — the item's owner team is also emailed each alert (or one email per digest) when the
 *   installation has a mailer (#6384); the hint says so.
 *
 * Announcements go to the workspace's webhooks and to the item's owner team (their inbox and chat
 * channel). A version made with **Check now** is never announced. Saving needs `imports:edit`.
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/app/components/ui/Select';
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';
import {
  DEFAULT_DRIFT_SETTINGS,
  driftSettingsSummary,
  DRIFT_SEVERITY_VIEW,
  fetchDriftSettings,
  saveDriftSettings,
  type CatalogDriftSettings,
} from './catalogDriftModel';

export interface CatalogDriftAlertsDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Open or close it. */
  onOpenChange: (open: boolean) => void;
}

/** The three severity toggles, most severe first. */
const SEVERITY_FIELDS = [
  { key: 'notifyBreaking', severity: 'breaking' },
  { key: 'notifyDangerous', severity: 'dangerous' },
  { key: 'notifySafe', severity: 'safe' },
] as const;

/**
 * Render the dialog. See {@link CatalogDriftAlertsDialogProps}.
 *
 * @returns The dialog.
 */
export function CatalogDriftAlertsDialog({ open, onOpenChange }: CatalogDriftAlertsDialogProps) {
  const returnFocus = useReturnFocus(open);
  const [settings, setSettings] = React.useState<CatalogDriftSettings | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadError(null);
    setSaveError(null);
    fetchDriftSettings()
      .then((loaded) => {
        if (!cancelled) setSettings({ ...DEFAULT_DRIFT_SETTINGS, ...loaded });
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : 'The drift alert settings could not be loaded.');
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const update = (patch: Partial<CatalogDriftSettings>) =>
    setSettings((current) => (current ? { ...current, ...patch } : current));

  const handleSave = async () => {
    if (!settings) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveDriftSettings(settings);
      onOpenChange(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'The drift alert settings could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const digest = settings?.delivery === 'daily_digest';

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : undefined)}>
      <DialogContent size="sm" onCloseAutoFocus={returnFocus} data-testid="catalog-drift-alerts-dialog">
        <DialogHeader>
          <DialogTitle>Drift alerts</DialogTitle>
          <DialogDescription>
            When a scheduled live refresh finds an API changed, Apiome tells this workspace&rsquo;s webhooks and the
            item&rsquo;s owner team. Every drift also shows a badge on the catalog card.
          </DialogDescription>
        </DialogHeader>

        {loadError ? (
          <div className="cid-refresh__error" role="alert" data-testid="catalog-drift-alerts-load-error">
            {loadError}
          </div>
        ) : !settings ? (
          <div className="cat-drift-alerts__loading" data-testid="catalog-drift-alerts-loading">
            Loading the drift alert settings…
          </div>
        ) : (
          <div className="cid-refresh-form">
            <fieldset className="cat-drift-alerts__group">
              <legend className="cat-drift-alerts__legend">Announce</legend>
              {SEVERITY_FIELDS.map(({ key, severity }) => (
                <label key={key} className="cid-refresh-form__check" htmlFor={`drift-alerts-${severity}`}>
                  <Checkbox
                    id={`drift-alerts-${severity}`}
                    checked={settings[key]}
                    onCheckedChange={(checked) => update({ [key]: checked === true })}
                    data-testid={`catalog-drift-alerts-${severity}`}
                  />
                  {DRIFT_SEVERITY_VIEW[severity].label} drift
                  <span className="cat-drift-alerts__hint">{DRIFT_SEVERITY_VIEW[severity].meaning}</span>
                </label>
              ))}
            </fieldset>

            <FormField label="Delivery" htmlFor="drift-alerts-delivery">
              <Select
                value={settings.delivery}
                onValueChange={(delivery) => update({ delivery: delivery as CatalogDriftSettings['delivery'] })}
              >
                <SelectTrigger id="drift-alerts-delivery" data-testid="catalog-drift-alerts-delivery">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="immediate">Right away</SelectItem>
                  <SelectItem value="daily_digest">Daily digest</SelectItem>
                </SelectContent>
              </Select>
            </FormField>

            {digest ? (
              <label className="cid-refresh-form__check" htmlFor="drift-alerts-breaking-immediate">
                <Checkbox
                  id="drift-alerts-breaking-immediate"
                  checked={settings.breakingImmediate}
                  onCheckedChange={(checked) => update({ breakingImmediate: checked === true })}
                  data-testid="catalog-drift-alerts-breaking-immediate"
                />
                Send breaking drift right away, not in the digest
              </label>
            ) : null}

            <label className="cid-refresh-form__check" htmlFor="drift-alerts-email">
              <Checkbox
                id="drift-alerts-email"
                checked={settings.emailEnabled}
                onCheckedChange={(checked) => update({ emailEnabled: checked === true })}
                data-testid="catalog-drift-alerts-email"
              />
              Email me about drift too
              <span className="cat-drift-alerts__hint">Emails the item’s owner team when email is set up.</span>
            </label>

            <div className="cat-drift-alerts__summary" data-testid="catalog-drift-alerts-summary">
              {driftSettingsSummary(settings)}
            </div>

            {saveError ? (
              <div className="cid-refresh__error" role="alert" data-testid="catalog-drift-alerts-error">
                {saveError}
              </div>
            ) : null}
          </div>
        )}

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
            disabled={saving || !settings}
            title={saving ? 'Saving the drift alert settings' : !settings ? 'The settings are still loading' : undefined}
            onClick={() => void handleSave()}
            data-testid="catalog-drift-alerts-save"
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

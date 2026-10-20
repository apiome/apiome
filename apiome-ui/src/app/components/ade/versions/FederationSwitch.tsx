'use client';

/**
 * The project's federation switch on the Versions → Sources tab — V2-REPO-8.2 (#2806).
 *
 * On (the default): each repository file imported into the project is merged with the other
 * contributing files into one API (REPO-5.7). Off: each import replaces the API with the importing
 * file alone. The switch applies to the next import; existing versions are not changed. The sentence
 * under it always says what the current position does, so its effect never has to be guessed.
 *
 * apiome-rest enforces `projects:edit` on the change and audits it
 * (`repository.federation_toggled`).
 */

import * as React from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Label } from '@/app/components/ui/Label';
import { Switch } from '@/app/components/ui/Switch';
import { FEDERATION_SWITCH_COPY, parseFederationSetting } from '@lib/repository-federation';

export interface FederationSwitchProps {
  /** The project. */
  projectId: string;
  /** Called with the stored value after a successful change. */
  onChanged?: (enabled: boolean) => void;
}

const LOAD_ERROR = 'Could not read the federation setting.';
const SAVE_ERROR = 'Could not change the federation setting. Try again.';

/**
 * Render the switch. See {@link FederationSwitchProps}.
 *
 * @returns The switch with its explanation, or an error.
 */
export function FederationSwitch({ projectId, onChanged }: FederationSwitchProps): React.JSX.Element {
  const [enabled, setEnabled] = React.useState<boolean | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const url = `/api/projects/${encodeURIComponent(projectId)}/repository-federation`;

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(url);
        const payload = await response.json().catch(() => null);
        const parsed = response.ok ? parseFederationSetting(payload) : null;
        if (cancelled) return;
        if (parsed === null) setError((payload as { error?: string } | null)?.error || LOAD_ERROR);
        else setEnabled(parsed);
      } catch {
        if (!cancelled) setError(LOAD_ERROR);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url]);

  const change = async (next: boolean) => {
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      });
      const payload = await response.json().catch(() => null);
      const parsed = response.ok ? parseFederationSetting(payload) : null;
      if (parsed === null) {
        setError((payload as { error?: string } | null)?.error || SAVE_ERROR);
      } else {
        setEnabled(parsed);
        onChanged?.(parsed);
      }
    } catch {
      setError(SAVE_ERROR);
    } finally {
      setSaving(false);
    }
  };

  const switchId = `federation-switch-${projectId}`;
  return (
    <div className="fed-switch" data-testid="federation-switch">
      <div className="fed-switch__row">
        <div className="fed-switch__text">
          <span className="fed-switch__label">
            <Label htmlFor={switchId}>Federation</Label>
            {enabled !== null ? (
              <Badge variant={enabled ? 'ok' : 'outline'} data-testid="federation-state">
                {enabled ? 'On' : 'Off'}
              </Badge>
            ) : null}
          </span>
          {enabled !== null ? (
            <p className="fed-note" data-testid="federation-explanation">
              {enabled ? FEDERATION_SWITCH_COPY.on : FEDERATION_SWITCH_COPY.off} Applies to the next import.
            </p>
          ) : null}
        </div>
        <Switch
          id={switchId}
          checked={enabled ?? false}
          disabled={enabled === null || saving}
          onCheckedChange={(next) => void change(next)}
          aria-label="Merge repository files into one API"
          data-testid="federation-toggle"
        />
      </div>
      {error ? (
        <Alert variant="error" data-testid="federation-switch-error">
          {error}
        </Alert>
      ) : null}
    </div>
  );
}

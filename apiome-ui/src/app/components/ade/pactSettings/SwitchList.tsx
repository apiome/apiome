'use client';

/**
 * A group of switches with one **Save** — the commit-status switches of **CI and commit statuses** and
 * the agent switches of **Agents** (PFX-8.15, #7312). A switch that nothing enforces yet says so under
 * it; read-only, every switch is disabled and there is no Save.
 */

import * as React from 'react';
import { Button } from '@/app/components/ui';
import { Switch } from '@/app/components/ui/Switch';
import type { SwitchSpec } from '@lib/pact-contract-settings';

/**
 * The switches.
 *
 * @param props - The switches, their saved values, whether they may be changed, and what Save does.
 * @returns The list and its Save.
 */
export function SwitchList<K extends string>({
  id,
  specs,
  saved,
  readOnly,
  saveLabel,
  onSave,
}: {
  id: string;
  specs: ReadonlyArray<SwitchSpec<K>>;
  saved: Record<K, boolean>;
  readOnly: boolean;
  saveLabel: string;
  onSave: (values: Record<K, boolean>) => Promise<void>;
}) {
  const [values, setValues] = React.useState<Record<K, boolean>>(saved);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  React.useEffect(() => setValues(saved), [saved]);
  const changed = specs.some((spec) => values[spec.key] !== saved[spec.key]);

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await onSave(values);
      setMessage({ tone: 'ok', text: 'Saved.' });
    } catch (caught) {
      setMessage({ tone: 'error', text: caught instanceof Error ? caught.message : 'Could not save.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pcx-switches" data-testid={`${id}-switches`}>
      {specs.map((spec) => (
        <div className="pcx-switch-row" key={spec.key} data-testid={`${id}-${spec.key}`}>
          <div>
            <div className="pcx-switch-row__title" id={`${id}-${spec.key}-label`}>
              {spec.title}
            </div>
            <div className="ppx__muted" id={`${id}-${spec.key}-hint`}>
              {spec.hint}
              {spec.notYet ? <span className="pcx-switch-row__note"> {spec.notYet}</span> : null}
            </div>
          </div>
          <Switch
            checked={values[spec.key]}
            onCheckedChange={(value) => {
              setValues((current) => ({ ...current, [spec.key]: value }));
              setMessage(null);
            }}
            disabled={readOnly || busy}
            aria-labelledby={`${id}-${spec.key}-label`}
            aria-describedby={`${id}-${spec.key}-hint`}
            data-testid={`${id}-${spec.key}-switch`}
          />
        </div>
      ))}
      {message ? (
        <p
          className={message.tone === 'ok' ? 'ppx__muted' : 'ppx__error'}
          role={message.tone === 'ok' ? 'status' : 'alert'}
          data-testid={`${id}-message`}
        >
          {message.text}
        </p>
      ) : null}
      {!readOnly ? (
        <div className="ppx__actions">
          <Button onClick={() => void save()} disabled={busy || !changed} data-testid={`${id}-save`}>
            {busy ? 'Saving…' : saveLabel}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export default SwitchList;

'use client';

/**
 * The workspace's external reference policy, on the **References** tab — COA-2.8 (#7051).
 *
 * Everyone sees the policy in force (and whether the deployment allows fetching at all), so a
 * **Blocked** reference explains itself. A tenant administrator can **Change policy**: **Block**
 * fetches nothing, **Fetch** fetches any public host (only the allowlisted ones when the allowlist
 * is not empty) and **Fetch allowlisted hosts only** requires an allowlist. The same policy governs
 * repository scans.
 */

import { useId, useState } from 'react';
import { ShieldCheck } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { FormField } from '@/app/components/ui/FormField';
import { Textarea } from '@/app/components/ui/Textarea';

import {
  MODE_LABEL,
  parseAllowlist,
  policySummary,
  saveExternalRefPolicy,
  type ExternalRefMode,
  type ExternalRefPolicy,
} from './projectReferencesApi';

/** Props for {@link ExternalRefPolicyCard}. */
export interface ExternalRefPolicyCardProps {
  /** The policy in force. */
  policy: ExternalRefPolicy;
  /** Called with the saved policy. */
  onSaved: (policy: ExternalRefPolicy) => void;
}

const MODES: ExternalRefMode[] = ['block', 'inline', 'proxy-fetch'];

/**
 * Render the card. See {@link ExternalRefPolicyCardProps}.
 *
 * @returns The card.
 */
export function ExternalRefPolicyCard({ policy, onSaved }: ExternalRefPolicyCardProps) {
  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<ExternalRefMode>(policy.mode);
  const [allowlist, setAllowlist] = useState(policy.allowlist.join('\n'));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const modeId = useId();
  const listId = useId();

  const patterns = parseAllowlist(allowlist);
  const problem = mode === 'proxy-fetch' && patterns.length === 0 ? 'Add at least one host.' : null;

  const startEditing = () => {
    setMode(policy.mode);
    setAllowlist(policy.allowlist.join('\n'));
    setError(null);
    setEditing(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const saved = await saveExternalRefPolicy(mode, patterns);
      onSaved(saved);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The policy could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rfx-policy" data-testid="external-ref-policy">
      <div className="rfx-policy__head">
        <ShieldCheck aria-hidden className="rfx-policy__icon" />
        <span className="rfx-policy__title">External reference policy</span>
        <span className="hive-quiet" data-testid="external-ref-policy-summary">
          {policySummary(policy)}
        </span>
        {policy.can_edit && !editing ? (
          <Button variant="ghost" size="sm" onClick={startEditing} data-testid="external-ref-policy-edit">
            Change policy
          </Button>
        ) : null}
      </div>
      {!policy.can_edit ? (
        <p className="hive-quiet">Workspace administrators can change it. It also applies to repository scans.</p>
      ) : null}

      {editing ? (
        <div className="xstd-stack xstd-stack--tight rfx-policy__form">
          <FormField label="Mode" htmlFor={modeId}>
            <select
              id={modeId}
              className="hive-control vovl-select"
              value={mode}
              onChange={(event) => setMode(event.target.value as ExternalRefMode)}
              data-testid="external-ref-policy-mode"
            >
              {MODES.map((option) => (
                <option key={option} value={option}>
                  {MODE_LABEL[option]}
                </option>
              ))}
            </select>
          </FormField>
          <FormField
            label="Allowed hosts"
            htmlFor={listId}
            helperText="One per line: schemas.acme.com, *.acme.com (subdomains), or * (any host). Empty with Fetch means any public host."
            error={problem ?? undefined}
          >
            <Textarea
              id={listId}
              className="xstd-mono"
              rows={3}
              value={allowlist}
              onChange={(event) => setAllowlist(event.target.value)}
              data-testid="external-ref-policy-allowlist"
            />
          </FormField>
          {error ? (
            <p className="xstd-notice" data-tone="warn" role="alert" data-testid="external-ref-policy-error">
              {error}
            </p>
          ) : null}
          <div className="vovl-actions">
            <Button
              variant="primary"
              onClick={() => void handleSave()}
              disabled={saving || !!problem}
              title={saving ? 'Saving the policy' : (problem ?? undefined)}
              data-testid="external-ref-policy-save"
            >
              {saving ? 'Saving…' : 'Save policy'}
            </Button>
            <Button
              variant="outline"
              onClick={() => setEditing(false)}
              disabled={saving}
              title={saving ? 'Wait for the policy to save' : undefined}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

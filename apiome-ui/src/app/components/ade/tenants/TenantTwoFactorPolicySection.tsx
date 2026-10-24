'use client';

/**
 * The manage drawer's **Security** section — TFA-1.3 (#5657).
 *
 * One workspace setting with one parameter:
 *
 * - **Require two-factor** — every member must turn on two-factor authentication.
 * - **Grace period** — days (0–90, default 7) a member without it may keep working. A member's
 *   deadline is the later of the requirement being turned on and the member joining, plus these
 *   days. Until then they see a banner; after it, the app asks them to set up two-factor before
 *   anything else.
 *
 * Under the form, a facts line counts active members with two-factor, in their grace period and
 * overdue, and links to the Members page, which shows who is who. Reading needs `members:view` and
 * saving `members:edit` (REST enforces both); every change is audited as `two_factor_policy.update`.
 * The section reads the session's current tenant, like the MCP and Ownership sections.
 */

import * as React from 'react';
import Link from 'next/link';
import { Lock } from 'lucide-react';
import { Alert, Button, FactsLine, Input, Label, LoadingState, Switch } from '@/app/components/ui';
import {
  DEFAULT_TWO_FACTOR_GRACE_DAYS,
  MAX_TWO_FACTOR_GRACE_DAYS,
  isValidGraceDays,
  type TwoFactorPolicy,
} from '@lib/two-factor-policy';
import { fetchTwoFactorPolicy, saveTwoFactorPolicy } from './twoFactorPolicyApi';

/** Props for {@link TenantTwoFactorPolicySection}. */
export interface TenantTwoFactorPolicySectionProps {
  /** Whether the reader administers the tenant; others see the policy read-only. */
  isAdmin: boolean;
  /** Where the Members page is, for the "see who" link. */
  membersPageHref: string;
  /** Reports unsaved changes, so the drawer can mark the tab. */
  onDirtyChange?: (dirty: boolean) => void;
}

/**
 * The Security section.
 *
 * @param props - See {@link TenantTwoFactorPolicySectionProps}.
 * @returns The form, its compliance line and the save row.
 */
export default function TenantTwoFactorPolicySection({
  isAdmin,
  membersPageHref,
  onDirtyChange,
}: TenantTwoFactorPolicySectionProps) {
  const [policy, setPolicy] = React.useState<TwoFactorPolicy | null>(null);
  const [required, setRequired] = React.useState(false);
  const [graceText, setGraceText] = React.useState(String(DEFAULT_TWO_FACTOR_GRACE_DAYS));
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  const reset = React.useCallback((next: TwoFactorPolicy) => {
    setPolicy(next);
    setRequired(next.require_two_factor);
    setGraceText(String(next.grace_days));
  }, []);

  React.useEffect(() => {
    let live = true;
    fetchTwoFactorPolicy()
      .then((next) => live && reset(next))
      .catch((caught: unknown) => live && setError(caught instanceof Error ? caught.message : 'Could not load the policy'));
    return () => {
      live = false;
    };
  }, [reset]);

  const graceDays = graceText.trim() === '' ? NaN : Number(graceText);
  const graceValid = isValidGraceDays(graceDays);
  const dirty =
    policy !== null &&
    (required !== policy.require_two_factor || (graceValid && graceDays !== policy.grace_days) || !graceValid);
  React.useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

  const save = async () => {
    if (!graceValid) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      reset(await saveTwoFactorPolicy({ require_two_factor: required, grace_days: graceDays }));
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the policy');
    } finally {
      setSaving(false);
    }
  };

  const readOnly = !isAdmin;
  const turningOn = policy !== null && required && !policy.require_two_factor;

  return (
    <section aria-labelledby="tnt-security-heading" className="space-y-4" data-testid="tenant-two-factor-policy">
      <div className="min-w-0">
        <h3 id="tnt-security-heading" className="tnt-section-title">
          Security
        </h3>
        <p className="tnt-section-desc">Whether every member of this workspace must use two-factor authentication.</p>
      </div>

      {readOnly ? (
        <p className="tnt-lock-note">
          <Lock className="size-[var(--icon-dense)] shrink-0" aria-hidden />
          Only administrators can change the two-factor policy.
        </p>
      ) : null}
      {error ? <Alert variant="error">{error}</Alert> : null}

      {!policy && !error ? (
        <LoadingState message="Loading the two-factor policy…" minHeightClassName="min-h-[8rem]" />
      ) : policy ? (
        <>
          <div className="tnt-own-switch">
            <Switch
              id="tnt-require-two-factor"
              checked={required}
              disabled={readOnly || saving}
              onCheckedChange={(next) => {
                setRequired(next);
                setSaved(false);
              }}
              data-testid="tenant-require-two-factor"
            />
            <div className="min-w-0">
              <Label htmlFor="tnt-require-two-factor">Require two-factor</Label>
              <p className="tnt-section-desc">
                Members without two-factor see a reminder. When their grace period ends they must set it up before they
                can use the app. API keys are not affected.
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="tnt-two-factor-grace" className="block">
              Grace period (days)
            </Label>
            <Input
              id="tnt-two-factor-grace"
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_TWO_FACTOR_GRACE_DAYS}
              step={1}
              className="tnt-2fa-grace"
              value={graceText}
              disabled={readOnly || saving}
              aria-invalid={!graceValid}
              aria-describedby="tnt-two-factor-grace-hint"
              onChange={(event) => {
                setGraceText(event.target.value);
                setSaved(false);
              }}
              data-testid="tenant-two-factor-grace"
            />
            <p id="tnt-two-factor-grace-hint" className="tnt-section-desc">
              {graceValid
                ? 'Counted from when the requirement is turned on, or from when a member joins if that is later.'
                : `Enter a whole number of days from 0 to ${MAX_TWO_FACTOR_GRACE_DAYS}.`}
            </p>
          </div>

          {turningOn ? (
            <Alert variant="info" role="note" data-testid="tenant-two-factor-turning-on">
              Saving starts everyone&apos;s grace period now.
            </Alert>
          ) : null}

          {policy.require_two_factor ? (
            <div className="space-y-1" data-testid="tenant-two-factor-compliance">
              <FactsLine
                page="tenant-two-factor"
                aria-label="Two-factor compliance"
                facts={[
                  { id: 'enabled', value: policy.compliance.enabled, label: 'with two-factor' },
                  { id: 'grace', value: policy.compliance.grace, label: 'in grace period' },
                  { id: 'overdue', value: policy.compliance.overdue, label: 'overdue' },
                ]}
              />
              <Link href={membersPageHref} className="tnt-section-desc underline">
                See who on the Members page
              </Link>
            </div>
          ) : null}

          {readOnly ? null : (
            <div className="flex items-center gap-3">
              <Button
                onClick={() => void save()}
                disabled={!dirty || !graceValid || saving}
                data-testid="tenant-two-factor-save"
              >
                {saving ? 'Saving…' : 'Save changes'}
              </Button>
              {saved ? (
                <span className="tnt-section-desc" role="status">
                  Saved.
                </span>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

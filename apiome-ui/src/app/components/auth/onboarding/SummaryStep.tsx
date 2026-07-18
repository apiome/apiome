'use client';

import { ArrowLeft, BadgeCheck, Check, Loader2 } from 'lucide-react';
import { FREE_LICENSE_SUMMARY } from '@lib/auth/free-license';
import { Button } from '../../ui/Button';

/** Inputs and callbacks of the review step. */
export interface SummaryStepProps {
  /** Organization name about to be created. */
  name: string;
  /** Slug about to be created. */
  slug: string;
  /** Provisioning error to display, if the last confirm attempt failed. */
  error: string | null;
  /** True while the create call is in flight (disables both actions). */
  submitting: boolean;
  /** Return to the organization step. */
  onBack: () => void;
  /** Create the tenant. */
  onConfirm: () => void;
}

/**
 * Third wizard step (OLO-4.1): review before confirm. Shows the entered
 * organization details and the Free license the tenant will start on
 * ({@link FREE_LICENSE_SUMMARY}) — the acceptance criterion is that the user
 * sees the plan before anything is created.
 */
export function SummaryStep({ name, slug, error, submitting, onBack, onConfirm }: SummaryStepProps) {
  return (
    <div data-testid="onboarding-step-summary">
      <h1
        id="first-tenant-onboarding-title"
        className="text-xl font-bold text-gray-900 dark:text-white"
      >
        Review and create
      </h1>
      <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
        Here&apos;s what will be created. You can change details later in tenant settings.
      </p>

      <dl className="mt-6 space-y-2 rounded-lg border border-gray-200 p-4 text-left text-sm dark:border-gray-700">
        <div className="flex justify-between gap-4">
          <dt className="text-gray-500 dark:text-gray-400">Organization</dt>
          <dd className="font-medium text-gray-900 dark:text-white">{name}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-gray-500 dark:text-gray-400">URL slug</dt>
          <dd className="font-mono text-gray-900 dark:text-white">{slug}</dd>
        </div>
      </dl>

      <section
        aria-label={`${FREE_LICENSE_SUMMARY.planName} plan summary`}
        className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50/50 p-4 text-left dark:border-indigo-800 dark:bg-indigo-900/20"
        data-testid="free-license-summary"
      >
        <div className="flex items-center gap-2">
          <BadgeCheck aria-hidden="true" className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
            {FREE_LICENSE_SUMMARY.planName} plan
          </h2>
        </div>
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
          {FREE_LICENSE_SUMMARY.description}
        </p>
        <ul className="mt-3 space-y-1 text-sm text-gray-700 dark:text-gray-300">
          {FREE_LICENSE_SUMMARY.limits.map((limit) => (
            <li key={limit.label} className="flex justify-between gap-4">
              <span>{limit.label}</span>
              <span className="font-medium">{limit.value}</span>
            </li>
          ))}
          {FREE_LICENSE_SUMMARY.includes.map((item) => (
            <li key={item} className="flex items-start gap-2">
              <Check
                aria-hidden="true"
                className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
              />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-left text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400"
        >
          {error}
        </div>
      )}

      <div className="mt-6 flex justify-between gap-3">
        <Button type="button" variant="outline" disabled={submitting} onClick={onBack}>
          <ArrowLeft aria-hidden="true" className="h-4 w-4" />
          Back
        </Button>
        <Button type="button" disabled={submitting} onClick={onConfirm}>
          {submitting && <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />}
          {submitting ? 'Creating…' : 'Create organization'}
        </Button>
      </div>
    </div>
  );
}

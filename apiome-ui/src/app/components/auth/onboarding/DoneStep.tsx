'use client';

import { ArrowRight, CircleCheck, Loader2 } from 'lucide-react';
import { Button } from '../../ui/Button';

/** Inputs and callbacks of the completion step. */
export interface DoneStepProps {
  /** Name of the tenant that was just created. */
  tenantName: string;
  /** True while the session update + dashboard navigation is in flight. */
  navigating: boolean;
  /** Activate the new tenant and land in its dashboard. */
  onGoToDashboard: () => void;
}

/**
 * Terminal wizard step (OLO-4.1): the tenant exists; the only remaining action
 * activates it in the session and lands the user in the new tenant's
 * dashboard (the wizard's completion acceptance criterion).
 */
export function DoneStep({ tenantName, navigating, onGoToDashboard }: DoneStepProps) {
  return (
    <div className="text-center" data-testid="onboarding-step-done">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-100 dark:bg-emerald-900/30">
        <CircleCheck aria-hidden="true" className="h-7 w-7 text-emerald-600 dark:text-emerald-400" />
      </div>
      <h1
        id="first-tenant-onboarding-title"
        className="text-xl font-bold text-gray-900 dark:text-white"
      >
        {tenantName} is ready
      </h1>
      <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
        Your organization was created on the Free plan and you&apos;re its administrator.
      </p>
      <div className="mt-6 flex justify-center">
        <Button disabled={navigating} onClick={onGoToDashboard}>
          {navigating ? (
            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
          ) : (
            <ArrowRight aria-hidden="true" className="h-4 w-4" />
          )}
          Go to your dashboard
        </Button>
      </div>
    </div>
  );
}

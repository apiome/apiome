'use client';

import { Building2, ArrowRight, LogOut, RefreshCw } from 'lucide-react';
import { Button } from '../../ui/Button';

/** Callbacks for the welcome step's three actions. */
export interface WelcomeStepProps {
  /** Advance to the organization step. */
  onGetStarted: () => void;
  /** Re-check memberships (for users expecting an invitation). */
  onCheckAgain: () => void;
  /** Sign out back to the login page. */
  onSignOut: () => void;
}

/**
 * First wizard step (OLO-4.1): explains why the user is here — their account
 * belongs to no tenant — and offers the only useful actions: start setup,
 * re-check memberships (invited users), or sign out. There is deliberately no
 * dismiss control; a tenant-less user has no other surface to use.
 */
export function WelcomeStep({ onGetStarted, onCheckAgain, onSignOut }: WelcomeStepProps) {
  return (
    <div className="text-center" data-testid="onboarding-step-welcome">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-indigo-900/30 dark:to-purple-900/30">
        <Building2 aria-hidden="true" className="h-7 w-7 text-indigo-600 dark:text-indigo-400" />
      </div>
      <h1
        id="first-tenant-onboarding-title"
        className="text-xl font-bold text-gray-900 dark:text-white"
      >
        Let&apos;s set up your first tenant
      </h1>
      <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
        Your account isn&apos;t a member of any tenant yet. This short setup creates your
        organization so you can start building.
      </p>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-500">
        Expecting an invitation? Once a tenant administrator adds you, check again to continue.
      </p>
      <div className="mt-6 flex flex-col justify-center gap-3">
        <Button onClick={onGetStarted}>
          Set up your organization
          <ArrowRight aria-hidden="true" className="h-4 w-4" />
        </Button>
        <div className="flex flex-col justify-center gap-3 sm:flex-row">
          <Button variant="outline" onClick={onCheckAgain}>
            <RefreshCw aria-hidden="true" className="h-4 w-4" />
            Check again
          </Button>
          <Button variant="outline" onClick={onSignOut}>
            <LogOut aria-hidden="true" className="h-4 w-4" />
            Sign out
          </Button>
        </div>
      </div>
    </div>
  );
}

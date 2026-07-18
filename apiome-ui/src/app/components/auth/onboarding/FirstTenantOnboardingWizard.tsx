'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { signOut, useSession } from 'next-auth/react';
import { Check } from 'lucide-react';
import { DEFAULT_LOGIN_LANDING } from '@lib/auth/cookie-options';
import { provisionFirstTenant } from '@lib/auth/first-tenant-actions';
import { cn } from '@lib/utils';
import {
  FIRST_TENANT_WIZARD_PROGRESS,
  FIRST_TENANT_WIZARD_STEPS,
  type FirstTenantWizardStep,
} from './wizard-steps';
import { WelcomeStep } from './WelcomeStep';
import { OrganizationStep, type OrganizationStepValues } from './OrganizationStep';
import { SummaryStep } from './SummaryStep';
import { DoneStep } from './DoneStep';

/**
 * First-tenant onboarding wizard (OLO-4.1, #4205), mounted by
 * `FirstTenantOnboardingGuard` in place of any /ade route content whenever the
 * authenticated user has zero tenant memberships.
 *
 * Steps: welcome → organization (name/slug; polished by OLO-4.2) → summary
 * (Free license shown before confirm) → done. The wizard is deliberately not
 * dismissible — a tenant-less user has nothing else to see — so the only exits
 * are completing setup, being added to a tenant ("Check again"), or signing
 * out.
 *
 * On confirm the tenant is provisioned by the `provisionFirstTenant` server
 * action; completion activates the new tenant in the session (the same
 * `useSession().update({ current_tenant_id })` contract the tenant switcher
 * uses) and lands the user in the new tenant's dashboard.
 */
export function FirstTenantOnboardingWizard() {
  const router = useRouter();
  const { update } = useSession();

  const [step, setStep] = useState<FirstTenantWizardStep>('welcome');
  const [orgName, setOrgName] = useState('');
  const [slug, setSlug] = useState('');
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [navigating, setNavigating] = useState(false);
  const [tenant, setTenant] = useState<{ id: string; name: string; slug: string } | null>(null);

  /** Stores the organization step's validated values and moves to review. */
  const handleOrganizationContinue = (values: OrganizationStepValues) => {
    setOrgName(values.name);
    setSlug(values.slug);
    setSubmitError(null);
    setStep('summary');
  };

  /** Runs provisioning; success reaches `done`, failure stays on the summary. */
  const handleConfirm = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await provisionFirstTenant(orgName, slug);
      if (result.success) {
        setTenant(result.tenant);
        setStep('done');
      } else {
        setSubmitError(result.error);
      }
    } catch (error) {
      console.error('[FirstTenantOnboardingWizard] provisioning failed:', error);
      setSubmitError('Something went wrong while creating your organization. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  /** Activates the new tenant in the session, then lands in its dashboard. */
  const handleGoToDashboard = async () => {
    if (!tenant) return;
    setNavigating(true);
    try {
      await update({ current_tenant_id: tenant.id });
    } catch (error) {
      // Non-fatal: the JWT callback re-derives the active tenant on the next
      // request, so landing without the eager update still works.
      console.error('[FirstTenantOnboardingWizard] session update failed:', error);
    } finally {
      // Refresh re-runs the onboarding guard, which now sees a membership and
      // renders the dashboard route instead of the wizard.
      router.push(DEFAULT_LOGIN_LANDING);
      router.refresh();
    }
  };

  return (
    <main
      className="flex h-full items-center justify-center overflow-y-auto bg-gray-50 p-6 dark:bg-gray-900"
      data-testid="first-tenant-onboarding-wizard"
    >
      <section
        aria-labelledby="first-tenant-onboarding-title"
        className="w-full max-w-lg rounded-2xl border border-gray-200 bg-white p-8 shadow-sm dark:border-gray-700 dark:bg-gray-800"
      >
        <WizardProgress currentStep={step} />
        {step === 'welcome' && (
          <WelcomeStep
            onGetStarted={() => setStep('organization')}
            onCheckAgain={() => router.refresh()}
            onSignOut={() => signOut({ callbackUrl: '/login' })}
          />
        )}
        {step === 'organization' && (
          <OrganizationStep
            initialName={orgName}
            initialSlug={slug}
            onBack={() => setStep('welcome')}
            onContinue={handleOrganizationContinue}
          />
        )}
        {step === 'summary' && (
          <SummaryStep
            name={orgName}
            slug={slug}
            error={submitError}
            submitting={submitting}
            onBack={() => setStep('organization')}
            onConfirm={handleConfirm}
          />
        )}
        {step === 'done' && tenant && (
          <DoneStep
            tenantName={tenant.name}
            navigating={navigating}
            onGoToDashboard={handleGoToDashboard}
          />
        )}
      </section>
    </main>
  );
}

/**
 * Numbered progress header over the three setup steps (the terminal `done`
 * step renders every marker as completed).
 *
 * @param currentStep The wizard step currently shown.
 */
function WizardProgress({ currentStep }: { currentStep: FirstTenantWizardStep }) {
  const currentIndex = FIRST_TENANT_WIZARD_STEPS.indexOf(currentStep);

  return (
    <ol aria-label="Setup progress" className="mb-8 flex items-center justify-center gap-2">
      {FIRST_TENANT_WIZARD_PROGRESS.map(({ step, label }, index) => {
        const stepIndex = FIRST_TENANT_WIZARD_STEPS.indexOf(step);
        const isComplete = currentIndex > stepIndex;
        const isCurrent = currentStep === step;
        return (
          <li key={step} aria-current={isCurrent ? 'step' : undefined} className="flex items-center gap-2">
            {index > 0 && <span aria-hidden="true" className="h-px w-6 bg-gray-300 dark:bg-gray-600" />}
            <span
              className={cn(
                'flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold',
                isComplete &&
                  'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400',
                isCurrent && 'bg-indigo-600 text-white',
                !isComplete && !isCurrent &&
                  'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
              )}
            >
              {isComplete ? <Check aria-hidden="true" className="h-3.5 w-3.5" /> : index + 1}
            </span>
            <span
              className={cn(
                'text-xs font-medium',
                isCurrent ? 'text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'
              )}
            >
              {label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default FirstTenantOnboardingWizard;

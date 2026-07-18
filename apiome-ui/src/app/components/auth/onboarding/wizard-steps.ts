/**
 * Step model of the first-tenant onboarding wizard (OLO-4.1, #4205).
 *
 * Pure data + navigation helpers, kept separate from the components so the
 * ordering contract is unit-testable and later tickets (OLO-4.2 tenant-step
 * polish, OLO-4.4 invited-user path) can extend it without touching the shell.
 */

/** Identifier of each wizard step, in visit order. */
export type FirstTenantWizardStep = 'welcome' | 'organization' | 'summary' | 'done';

/** All steps in visit order. `done` is terminal and not shown in progress. */
export const FIRST_TENANT_WIZARD_STEPS: readonly FirstTenantWizardStep[] = [
  'welcome',
  'organization',
  'summary',
  'done',
];

/** Steps shown in the progress header, with their display labels. */
export const FIRST_TENANT_WIZARD_PROGRESS: ReadonlyArray<{
  step: FirstTenantWizardStep;
  label: string;
}> = [
  { step: 'welcome', label: 'Welcome' },
  { step: 'organization', label: 'Organization' },
  { step: 'summary', label: 'Review' },
];

/**
 * The step after `step`, or `step` itself when already at the end.
 *
 * @param step The current wizard step.
 * @returns The next step in visit order.
 */
export function nextWizardStep(step: FirstTenantWizardStep): FirstTenantWizardStep {
  const index = FIRST_TENANT_WIZARD_STEPS.indexOf(step);
  return FIRST_TENANT_WIZARD_STEPS[Math.min(index + 1, FIRST_TENANT_WIZARD_STEPS.length - 1)];
}

/**
 * The step before `step`, or `step` itself when already at the start.
 *
 * @param step The current wizard step.
 * @returns The previous step in visit order.
 */
export function previousWizardStep(step: FirstTenantWizardStep): FirstTenantWizardStep {
  const index = FIRST_TENANT_WIZARD_STEPS.indexOf(step);
  return FIRST_TENANT_WIZARD_STEPS[Math.max(index - 1, 0)];
}

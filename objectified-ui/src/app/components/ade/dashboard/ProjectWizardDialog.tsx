'use client';

import { useCallback, useMemo, useState } from 'react';
import { useSession } from 'next-auth/react';
import { Check, ChevronLeft, ChevronRight, Loader2, X } from 'lucide-react';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Alert } from '../../ui/Alert';
import { StepPath } from './projectWizard/StepPath';
import { StepBasics } from './projectWizard/StepBasics';
import { StepTemplate } from './projectWizard/StepTemplate';
import { StepReview } from './projectWizard/StepReview';
import {
  WIZARD_STEPS,
  type WizardStepId,
  createInitialWizardState,
} from './projectWizard/wizardTypes';
import { PROJECT_DOMAIN_CATEGORY_NONE } from '../../../utils/project-domain-categories';
import { createProject } from '../../../../../lib/db/helper';

export interface ProjectWizardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * Called once a project has been created successfully. The page is
   * responsible for refreshing the project list.
   */
  onCreated?: (projectId: string) => void;
}

const STEP_LABELS: Record<WizardStepId, { title: string; subtitle: string }> = {
  path: { title: 'Path', subtitle: 'How will you start?' },
  basics: { title: 'Basics', subtitle: 'Name & identity' },
  template: { title: 'Template', subtitle: 'OpenAPI starter' },
  review: { title: 'Review', subtitle: 'Confirm & create' },
};

type SessionUserExtensions = {
  current_tenant_id?: string;
  user_id?: string;
};

interface CreateResponse {
  success: boolean;
  error?: string;
  project?: { id: string };
}

export function ProjectWizardDialog({
  open,
  onOpenChange,
  onCreated,
}: ProjectWizardDialogProps) {
  const { data: session } = useSession();
  const sessionUser = session?.user as SessionUserExtensions | undefined;

  const [state, setState] = useState(() => createInitialWizardState());
  const [stepIndex, setStepIndex] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (isSubmitting) return;
      if (!next) {
        setState(createInitialWizardState());
        setStepIndex(0);
        setErrorMessage(null);
      }
      onOpenChange(next);
    },
    [onOpenChange, isSubmitting]
  );

  const currentStep = WIZARD_STEPS[stepIndex];

  const reviewWarnings = useMemo(() => {
    const issues: string[] = [];
    if (!state.basics.name.trim()) issues.push('Name is required.');
    if (!state.basics.slug.trim()) issues.push('Slug is required.');
    if (!sessionUser?.current_tenant_id) {
      issues.push('No tenant selected — pick a tenant before creating a project.');
    }
    if (!sessionUser?.user_id) {
      issues.push('Could not determine current user. Try signing out and back in.');
    }
    return issues;
  }, [state.basics, sessionUser]);

  const canAdvance = useMemo(() => {
    switch (currentStep) {
      case 'path':
        return state.path === 'manual';
      case 'basics':
        return (
          state.basics.name.trim().length > 0 && state.basics.slug.trim().length > 0
        );
      case 'template':
        return true;
      case 'review':
        return reviewWarnings.length === 0;
      default:
        return false;
    }
  }, [currentStep, state, reviewWarnings]);

  function goPrev() {
    setErrorMessage(null);
    setStepIndex((i) => Math.max(0, i - 1));
  }

  function goNext() {
    setErrorMessage(null);
    setStepIndex((i) => Math.min(WIZARD_STEPS.length - 1, i + 1));
  }

  async function handleCreate() {
    if (!sessionUser?.current_tenant_id || !sessionUser.user_id) {
      setErrorMessage('Missing tenant or user. Cannot create project.');
      return;
    }
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const metadata = { ...state.template.metadata };
      if (
        state.basics.domainCategory &&
        state.basics.domainCategory !== PROJECT_DOMAIN_CATEGORY_NONE
      ) {
        metadata.domainCategory = state.basics.domainCategory;
      }

      const result = await createProject(
        sessionUser.current_tenant_id,
        sessionUser.user_id,
        state.basics.name.trim(),
        state.basics.description.trim(),
        state.basics.slug.trim(),
        metadata
      );
      const response = JSON.parse(result) as CreateResponse;
      if (!response.success) {
        setErrorMessage(response.error || 'Failed to create project');
        return;
      }
      toast.success(`Project "${state.basics.name.trim()}" created`);
      onCreated?.(response.project?.id ?? '');
      handleOpenChange(false);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to create project');
    } finally {
      setIsSubmitting(false);
    }
  }

  const isLastStep = currentStep === 'review';

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="max-w-3xl w-full p-0 overflow-hidden"
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <div>
            <DialogTitle className="text-base">Create a new project</DialogTitle>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Step {stepIndex + 1} of {WIZARD_STEPS.length} &middot;{' '}
              {STEP_LABELS[currentStep].subtitle}
            </p>
          </div>
          <button
            type="button"
            onClick={() => handleOpenChange(false)}
            disabled={isSubmitting}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <ol className="flex items-stretch px-6 pt-4 pb-2 gap-2 text-xs">
          {WIZARD_STEPS.map((id, idx) => {
            const isActive = idx === stepIndex;
            const isComplete = idx < stepIndex;
            return (
              <li key={id} className="flex-1 min-w-0">
                <button
                  type="button"
                  onClick={() => idx <= stepIndex && setStepIndex(idx)}
                  disabled={idx > stepIndex || isSubmitting}
                  className={`w-full text-left rounded-md px-3 py-2 border transition-colors ${
                    isActive
                      ? 'border-indigo-500 bg-indigo-50/60 dark:bg-indigo-900/20'
                      : isComplete
                        ? 'border-emerald-200 dark:border-emerald-700/40 bg-emerald-50/60 dark:bg-emerald-900/10 hover:border-emerald-400'
                        : 'border-gray-200 dark:border-gray-700 opacity-60 cursor-not-allowed'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-semibold ${
                        isComplete
                          ? 'bg-emerald-500 text-white'
                          : isActive
                            ? 'bg-indigo-500 text-white'
                            : 'bg-gray-200 dark:bg-gray-700 text-gray-500'
                      }`}
                    >
                      {isComplete ? <Check className="w-3 h-3" /> : idx + 1}
                    </span>
                    <span
                      className={`font-semibold truncate ${
                        isActive ? 'text-indigo-700 dark:text-indigo-300' : ''
                      }`}
                    >
                      {STEP_LABELS[id].title}
                    </span>
                  </div>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="px-6 py-5 max-h-[60vh] overflow-y-auto space-y-4">
          {errorMessage ? <Alert variant="error">{errorMessage}</Alert> : null}

          {currentStep === 'path' ? (
            <StepPath
              value={state.path}
              onChange={(path) => setState((prev) => ({ ...prev, path }))}
            />
          ) : null}

          {currentStep === 'basics' ? (
            <StepBasics
              value={state.basics}
              onChange={(basics) => setState((prev) => ({ ...prev, basics }))}
            />
          ) : null}

          {currentStep === 'template' ? (
            <StepTemplate
              value={state.template}
              onChange={(template) => setState((prev) => ({ ...prev, template }))}
              onTemplatePicked={(suggested) => {
                setState((prev) => {
                  if (prev.basics.description.trim()) return prev;
                  return {
                    ...prev,
                    basics: { ...prev.basics, description: suggested },
                  };
                });
              }}
            />
          ) : null}

          {currentStep === 'review' ? (
            <StepReview state={state} warnings={reviewWarnings} />
          ) : null}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={stepIndex === 0 || isSubmitting}
            onClick={goPrev}
          >
            <ChevronLeft className="w-4 h-4 mr-1" /> Back
          </Button>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isSubmitting}
              onClick={() => handleOpenChange(false)}
            >
              Cancel
            </Button>
            {isLastStep ? (
              <Button
                type="button"
                size="sm"
                disabled={!canAdvance || isSubmitting}
                onClick={handleCreate}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-1 animate-spin" /> Creating…
                  </>
                ) : (
                  <>
                    <Check className="w-4 h-4 mr-1" /> Create project
                  </>
                )}
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                disabled={!canAdvance || isSubmitting}
                onClick={goNext}
              >
                Next <ChevronRight className="w-4 h-4 ml-1" />
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

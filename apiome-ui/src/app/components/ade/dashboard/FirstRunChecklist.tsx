'use client';

/**
 * Dashboard first-run checklist (#3614): a dismissible panel that guides a new user through the
 * core loop — create a project, add a class from a starter template, cut a version, publish it, and
 * view it in Browse. Step completion is derived from real dashboard stats (see
 * ./firstRunChecklist), and dismissal is persisted in localStorage. Uses only shared dashboard
 * tokens + UI primitives (no hardcoded styling).
 */

import { useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, Circle, Rocket, X, ArrowRight, ExternalLink } from 'lucide-react';

import { dashboardPanelClass } from './dashboardScreenClasses';
import { Badge } from '../../ui/Badge';
import { Button } from '../../ui/Button';
import { cn } from '../../../../../lib/utils';
import { BROWSE_APP_URL } from '../../../../../lib/app-urls';
import {
  type ChecklistSignal,
  type StepId,
  TOTAL_STEPS,
  allComplete,
  completedCount,
  deriveCompletion,
  isDismissed,
  setDismissed,
} from './firstRunChecklist';

interface StepDef {
  id: StepId;
  label: string;
  hint: string;
  href: string;
  external?: boolean;
}

const STEPS: StepDef[] = [
  { id: 'project', label: 'Create your first project', hint: 'Open the Designer to start a project.', href: '/ade/studio' },
  { id: 'class', label: 'Add a class from a starter template', hint: 'Browse the built-in templates to add a class.', href: '/ade/studio' },
  { id: 'version', label: 'Cut a version', hint: 'Snapshot your schema as a version.', href: '/ade/dashboard/versions' },
  { id: 'publish', label: 'Publish it', hint: 'Publish the version so it becomes browsable.', href: '/ade/dashboard/versions' },
  { id: 'browse', label: 'View it in Browse', hint: 'See your published spec render publicly.', href: BROWSE_APP_URL, external: true },
];

interface FirstRunChecklistProps {
  stats: ChecklistSignal;
}

export function FirstRunChecklist({ stats }: FirstRunChecklistProps) {
  // Lazily read the dismissal flag. Safe because this component is only mounted client-side after
  // the dashboard finishes loading (the parent gates on !isLoading), so it is never server-rendered
  // and there is no hydration mismatch; isDismissed() also returns false when storage is absent.
  const [dismissed, setDismissedState] = useState<boolean>(() => isDismissed());

  if (dismissed) return null;

  const done = deriveCompletion(stats);
  const completed = completedCount(stats);
  const finished = allComplete(stats);

  const handleDismiss = () => {
    setDismissed();
    setDismissedState(true);
  };

  return (
    <section className={cn(dashboardPanelClass, 'overflow-hidden')} aria-label="Getting started checklist">
      <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Rocket className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
          <div>
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">
              {finished ? "You're all set" : 'Get started'}
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {finished
                ? 'You have published a browsable spec — explore Browse or dismiss this.'
                : 'Reach a published, browsable spec in a few steps.'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={finished ? 'success' : 'secondary'} className="text-xs">
            {completed}/{TOTAL_STEPS} done
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleDismiss}
            aria-label="Dismiss getting-started checklist"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <ol className="p-3 sm:p-4 space-y-1">
        {STEPS.map((step, index) => {
          const isDone = done[step.id];
          const rowInner = (
            <div
              className={cn(
                'flex items-center gap-3 p-3 rounded-lg transition-colors',
                'hover:bg-gray-50 dark:hover:bg-gray-800/50',
              )}
            >
              {isDone ? (
                <CheckCircle2 className="h-5 w-5 flex-shrink-0 text-emerald-500" />
              ) : (
                <Circle className="h-5 w-5 flex-shrink-0 text-gray-300 dark:text-gray-600" />
              )}
              <div className="flex-1 min-w-0">
                <p
                  className={cn(
                    'text-sm font-medium',
                    isDone
                      ? 'text-gray-400 dark:text-gray-500 line-through'
                      : 'text-gray-800 dark:text-gray-100',
                  )}
                >
                  {index + 1}. {step.label}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">{step.hint}</p>
              </div>
              {step.external ? (
                <ExternalLink className="h-4 w-4 flex-shrink-0 text-gray-400 dark:text-gray-500" />
              ) : (
                <ArrowRight className="h-4 w-4 flex-shrink-0 text-gray-400 dark:text-gray-500" />
              )}
            </div>
          );

          return (
            <li key={step.id}>
              {step.external ? (
                <a href={step.href} target="_blank" rel="noopener noreferrer" className="block">
                  {rowInner}
                </a>
              ) : (
                <Link href={step.href} className="block">
                  {rowInner}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default FirstRunChecklist;

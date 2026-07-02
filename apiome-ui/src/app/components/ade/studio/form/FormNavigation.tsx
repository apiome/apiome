'use client';

import * as React from 'react';
import { Check, ChevronLeft, ChevronRight, Sparkles, Sliders } from 'lucide-react';
import { Button } from '../../../ui/Button';
import { cn } from '../../../../../../lib/utils';

/**
 * Navigation primitives for the dual-mode dialog forms.
 *
 * - FormViewModeToggle: segmented control that flips between "Guided" (step
 *   wizard) and "Advanced" (scrollable single pane with sidebar TOC).
 * - FormSectionNav: sticky left TOC used by Advanced mode, driven by the
 *   scroll-spy hook in useFormScrollSpy.ts.
 * - FormWizardStepper: top progress pills + Back/Next/Save controls used by
 *   Guided mode.
 */

export type FormViewMode = 'guided' | 'advanced';

export interface FormViewModeToggleProps {
  value: FormViewMode;
  onChange: (next: FormViewMode) => void;
  className?: string;
  disabled?: boolean;
}

const VIEW_MODES: Array<{ mode: FormViewMode; label: string; icon: React.ReactNode }> = [
  { mode: 'guided', label: 'Guided', icon: <Sparkles className="h-3.5 w-3.5" /> },
  { mode: 'advanced', label: 'Advanced', icon: <Sliders className="h-3.5 w-3.5" /> },
];

export const FormViewModeToggle: React.FC<FormViewModeToggleProps> = ({
  value,
  onChange,
  className,
  disabled,
}) => {
  return (
    <div
      role="tablist"
      aria-label="Form view mode"
      className={cn(
        'inline-flex items-center gap-0.5 rounded-lg border border-slate-200 bg-slate-100 p-0.5 dark:border-slate-700 dark:bg-slate-800',
        className,
      )}
    >
      {VIEW_MODES.map(({ mode, label, icon }) => {
        const active = value === mode;
        return (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={disabled}
            onClick={() => onChange(mode)}
            className={cn(
              'relative inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors',
              active
                ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200',
              disabled && 'cursor-not-allowed opacity-60',
            )}
          >
            <span className="inline-flex h-3.5 w-3.5 items-center justify-center">{icon}</span>
            {label}
          </button>
        );
      })}
    </div>
  );
};

export interface FormSectionNavItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  /** Optional group label that renders as an uppercase eyebrow above this item. */
  group?: string;
  /** Indicates that this section currently has non-default values. */
  changed?: boolean;
}

export interface FormSectionNavProps {
  items: FormSectionNavItem[];
  activeId: string;
  onSelect: (id: string) => void;
  className?: string;
  title?: string;
}

export const FormSectionNav: React.FC<FormSectionNavProps> = ({
  items,
  activeId,
  onSelect,
  className,
  title = 'Sections',
}) => {
  // Group items by their `group` field while preserving order.
  const groups: Array<{ group: string | undefined; items: FormSectionNavItem[] }> = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && last.group === item.group) {
      last.items.push(item);
    } else {
      groups.push({ group: item.group, items: [item] });
    }
  }

  return (
    <nav
      aria-label={title}
      className={cn(
        'sticky top-0 flex h-full w-56 shrink-0 flex-col overflow-y-auto border-r border-slate-200 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-900/40',
        className,
      )}
    >
      <div className="px-4 pt-5 pb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        {title}
      </div>
      <ul className="flex flex-col gap-0.5 px-2 pb-6">
        {groups.map((group, gi) => (
          <React.Fragment key={gi}>
            {group.group && (
              <li
                className={cn(
                  'px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500',
                  gi === 0 && 'pt-1',
                )}
              >
                {group.group}
              </li>
            )}
            {group.items.map((item) => {
              const active = item.id === activeId;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(item.id)}
                    aria-current={active ? 'true' : undefined}
                    className={cn(
                      'group flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-[13px] font-medium transition-colors',
                      active
                        ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100',
                    )}
                  >
                    {item.icon && (
                      <span
                        className={cn(
                          'flex h-3.5 w-3.5 shrink-0 items-center justify-center',
                          active ? 'text-indigo-500 dark:text-indigo-300' : 'text-slate-400 dark:text-slate-500',
                        )}
                      >
                        {item.icon}
                      </span>
                    )}
                    <span className="truncate">{item.label}</span>
                    {item.changed && (
                      <span
                        className="ml-auto inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
                        aria-label="Contains non-default values"
                      />
                    )}
                  </button>
                </li>
              );
            })}
          </React.Fragment>
        ))}
      </ul>
    </nav>
  );
};

export interface FormWizardStep {
  id: string;
  label: string;
  description?: string;
  icon?: React.ReactNode;
  /** When set, the step shows an error state in the indicator. */
  hasError?: boolean;
  /** When set, the step shows a completed check instead of its index. */
  complete?: boolean;
}

export interface FormWizardStepperProps {
  steps: FormWizardStep[];
  /** 0-based index of the currently visible step. */
  currentIndex: number;
  onStepSelect?: (index: number) => void;
  className?: string;
}

export const FormWizardStepper: React.FC<FormWizardStepperProps> = ({
  steps,
  currentIndex,
  onStepSelect,
  className,
}) => {
  return (
    <ol
      className={cn(
        'flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-slate-200 bg-white px-6 py-3 dark:border-slate-800 dark:bg-slate-900/60',
        className,
      )}
      aria-label="Progress"
    >
      {steps.map((step, index) => {
        const isCurrent = index === currentIndex;
        const isComplete = !!step.complete || index < currentIndex;
        const clickable = typeof onStepSelect === 'function';
        return (
          <li key={step.id} className="flex items-center gap-2">
            <button
              type="button"
              onClick={clickable ? () => onStepSelect?.(index) : undefined}
              disabled={!clickable}
              className={cn(
                'group inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors',
                isCurrent
                  ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-500/30'
                  : isComplete
                    ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200'
                    : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
                step.hasError && 'ring-1 ring-red-400 ring-offset-1 ring-offset-white dark:ring-offset-slate-900',
                clickable && !isCurrent && 'hover:bg-slate-200 dark:hover:bg-slate-700',
                !clickable && 'cursor-default',
              )}
              aria-current={isCurrent ? 'step' : undefined}
            >
              <span
                className={cn(
                  'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold',
                  isCurrent
                    ? 'bg-white/20 text-white'
                    : isComplete
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-300 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
                )}
              >
                {isComplete ? <Check className="h-3 w-3" /> : index + 1}
              </span>
              <span className="whitespace-nowrap">{step.label}</span>
            </button>
            {index < steps.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  'hidden h-px w-6 shrink-0 sm:inline-block',
                  index < currentIndex
                    ? 'bg-indigo-400 dark:bg-indigo-500'
                    : 'bg-slate-200 dark:bg-slate-700',
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
};

export interface FormWizardControlsProps {
  currentIndex: number;
  stepCount: number;
  onBack: () => void;
  onNext: () => void;
  onCancel?: () => void;
  onFinish?: () => void;
  nextDisabled?: boolean;
  finishDisabled?: boolean;
  finishLabel?: string;
  finishBusy?: boolean;
  className?: string;
  /** Extra nodes rendered on the far-left of the footer. */
  leading?: React.ReactNode;
}

export const FormWizardControls: React.FC<FormWizardControlsProps> = ({
  currentIndex,
  stepCount,
  onBack,
  onNext,
  onCancel,
  onFinish,
  nextDisabled,
  finishDisabled,
  finishLabel = 'Save',
  finishBusy,
  className,
  leading,
}) => {
  const isFirst = currentIndex === 0;
  const isLast = currentIndex === stepCount - 1;
  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-3', className)}>
      <div className="flex items-center gap-2">{leading}</div>
      <div className="flex items-center gap-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Button type="button" variant="outline" onClick={onBack} disabled={isFirst}>
          <ChevronLeft className="h-4 w-4" />
          Back
        </Button>
        {!isLast ? (
          <Button type="button" onClick={onNext} disabled={nextDisabled}>
            Next
            <ChevronRight className="h-4 w-4" />
          </Button>
        ) : (
          <Button type="button" onClick={onFinish} disabled={finishDisabled || finishBusy}>
            {finishBusy ? 'Saving…' : finishLabel}
          </Button>
        )}
      </div>
    </div>
  );
};

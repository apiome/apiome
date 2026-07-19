'use client';

/**
 * One scope selector in the Authoring header (UXE-1.2).
 *
 * Project, version and environment are the same control with different data,
 * so they share one implementation: identical keyboard behavior, identical
 * empty and disabled messaging, and a single place to fix any of it.
 */

import * as React from 'react';
import * as Select from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';
import { cn } from '@lib/utils';
import {
  authoringSelectContentClass,
  authoringSelectItemClass,
  authoringSelectTriggerClass,
} from '../authoringClasses';
import AuthoringIcon from './AuthoringIcon';

/** One selectable option. */
export type AuthoringScopeOption = {
  value: string;
  label: string;
  /** Secondary line shown under the label in the list. */
  hint?: string;
};

/** Props for {@link AuthoringScopeSelect}. */
export type AuthoringScopeSelectProps = {
  /** Accessible name, e.g. `Project`. */
  label: string;
  /** Lucide icon name shown in the trigger. */
  icon: string;
  options: readonly AuthoringScopeOption[];
  /** Selected value, or `''` when nothing is selected. */
  value: string;
  onValueChange: (value: string) => void;
  /** Shown in the trigger when nothing is selected. */
  placeholder: string;
  /** Shown in place of the list when there are no options. */
  emptyMessage: string;
  disabled?: boolean;
};

/**
 * Render a labeled scope selector.
 *
 * @param props - Label, icon, options and selection callbacks.
 */
export default function AuthoringScopeSelect({
  label,
  icon,
  options,
  value,
  onValueChange,
  placeholder,
  emptyMessage,
  disabled,
}: AuthoringScopeSelectProps) {
  /*
   * An empty or blocked selector stays focusable and openable rather than
   * being natively `disabled`. A disabled control leaves the tab order
   * entirely, so a keyboard or screen-reader user would never encounter the
   * Version control and would get no explanation of why it is unusable. Instead
   * the trigger opens onto `emptyMessage`, and the same sentence is bound as
   * the control's accessible description so it is announced on focus.
   */
  const isEmpty = options.length === 0;
  const showsExplanation = Boolean(disabled) || isEmpty;
  const descriptionId = `${React.useId()}-authoring-scope-hint`;

  return (
    <>
      {showsExplanation ? (
        <span id={descriptionId} className="sr-only">
          {emptyMessage}
        </span>
      ) : null}
      <Select.Root value={value} onValueChange={onValueChange}>
        <Select.Trigger
          className={authoringSelectTriggerClass}
          aria-label={label}
          aria-describedby={showsExplanation ? descriptionId : undefined}
        >
          <AuthoringIcon
            name={icon}
            className="h-4 w-4 shrink-0 text-gray-400 dark:text-gray-500"
          />
          <span className="truncate">
            <Select.Value placeholder={placeholder} />
          </span>
          <Select.Icon className="ml-auto">
            <ChevronDown className="h-4 w-4 text-gray-400" aria-hidden="true" />
          </Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Content className={authoringSelectContentClass} position="popper" sideOffset={6}>
            <Select.Viewport className="max-h-72 p-1">
              {options.length === 0 ? (
                <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">
                  {emptyMessage}
                </div>
              ) : (
                options.map((option) => (
                  <Select.Item
                    key={option.value}
                    value={option.value}
                    className={cn(authoringSelectItemClass)}
                  >
                    <Select.ItemIndicator className="absolute left-2 inline-flex items-center">
                      <Check
                        className="h-4 w-4 text-indigo-600 dark:text-indigo-400"
                        aria-hidden="true"
                      />
                    </Select.ItemIndicator>
                    <span className="flex flex-col">
                      <Select.ItemText>{option.label}</Select.ItemText>
                      {option.hint ? (
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          {option.hint}
                        </span>
                      ) : null}
                    </span>
                  </Select.Item>
                ))
              )}
            </Select.Viewport>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </>
  );
}

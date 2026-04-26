'use client';

import { Bot, FileText, type LucideIcon, PenLine, Sparkles, Upload } from 'lucide-react';
import type { WizardPath } from './wizardTypes';

export interface StepPathProps {
  value: WizardPath;
  onChange: (next: WizardPath) => void;
}

interface PathOption {
  id: WizardPath;
  label: string;
  description: string;
  Icon: LucideIcon;
  /** Disabled paths render with a "Coming soon" badge and can't be selected. */
  disabled?: boolean;
}

const PATH_OPTIONS: PathOption[] = [
  {
    id: 'manual',
    label: 'Start from scratch',
    description:
      'Pick a name and a starter template. You will add classes and properties yourself in the Studio.',
    Icon: PenLine,
  },
  {
    id: 'ai',
    label: 'Describe it to AI',
    description:
      'Tell the model what you are building and let it draft the initial schema. Good for prototyping.',
    Icon: Bot,
    disabled: true,
  },
  {
    id: 'import',
    label: 'Import an OpenAPI spec',
    description:
      'Upload an existing spec file or paste a URL. We will map it to classes, properties and tags.',
    Icon: Upload,
    disabled: true,
  },
];

export function StepPath({ value, onChange }: StepPathProps) {
  return (
    <div className="space-y-5">
      <header className="flex items-start gap-3">
        <div className="p-2 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300">
          <Sparkles className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold">How do you want to start?</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Pick the path that matches what you have on hand. You can always add classes
            after creation.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {PATH_OPTIONS.map(({ id, label, description, Icon, disabled }) => {
          const isSelected = value === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => !disabled && onChange(id)}
              disabled={disabled}
              className={`relative text-left rounded-lg border p-4 transition-colors ${
                disabled
                  ? 'border-gray-200 dark:border-gray-700 bg-gray-50/40 dark:bg-gray-900/40 opacity-70 cursor-not-allowed'
                  : isSelected
                    ? 'border-indigo-500 bg-indigo-50/60 dark:bg-indigo-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-700'
              }`}
            >
              {disabled ? (
                <span className="absolute top-3 right-3 text-[9px] uppercase font-semibold px-2 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                  Coming soon
                </span>
              ) : isSelected ? (
                <span className="absolute top-3 right-3 text-[9px] uppercase font-semibold px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300">
                  Selected
                </span>
              ) : null}
              <div
                className={`w-10 h-10 rounded-md flex items-center justify-center mb-3 ${
                  disabled
                    ? 'bg-gray-100 dark:bg-gray-800 text-gray-400'
                    : isSelected
                      ? 'bg-indigo-500 text-white'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                }`}
              >
                <Icon className="w-5 h-5" />
              </div>
              <p className="text-sm font-semibold">{label}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 leading-relaxed">
                {description}
              </p>
            </button>
          );
        })}
      </div>

      <p className="text-[11px] text-gray-500 dark:text-gray-400 inline-flex items-start gap-1.5">
        <FileText className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        AI and Import paths are on the roadmap. For now, the Manual path covers everything
        you need to ship a project end-to-end.
      </p>
    </div>
  );
}

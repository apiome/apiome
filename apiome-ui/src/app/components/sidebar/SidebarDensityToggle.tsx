'use client';

import * as React from 'react';
import { Rows3, Rows2, Square } from 'lucide-react';
import { useSidebarDensity, type SidebarDensity, DENSITY_LABELS } from './sidebar-theme';

const ORDER: SidebarDensity[] = ['compact', 'standard', 'comfortable'];

const ICONS: Record<SidebarDensity, React.ReactNode> = {
  compact: <Rows3 className="w-3.5 h-3.5" aria-hidden />,
  standard: <Rows2 className="w-3.5 h-3.5" aria-hidden />,
  comfortable: <Square className="w-3.5 h-3.5" aria-hidden />,
};

/**
 * Three-segment density toggle. Renders inline (e.g. inside a SidebarShell
 * footer or header actions slot). Persists via {@link useSidebarDensity}.
 */
export default function SidebarDensityToggle({ className }: { className?: string }) {
  const [density, setDensity] = useSidebarDensity();

  return (
    <div
      role="radiogroup"
      aria-label="Sidebar density"
      className={[
        'inline-flex items-center gap-0.5 p-0.5 rounded-md',
        'bg-slate-100/80 dark:bg-slate-900/80',
        'border border-slate-200 dark:border-slate-800',
        className ?? '',
      ].join(' ')}
    >
      {ORDER.map((value) => {
        const active = density === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            title={DENSITY_LABELS[value]}
            onClick={() => setDensity(value)}
            className={[
              'flex items-center justify-center w-6 h-6 rounded transition-colors',
              active
                ? 'bg-white dark:bg-slate-800 text-indigo-600 dark:text-indigo-400 shadow-sm ring-1 ring-slate-200 dark:ring-slate-700'
                : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100',
            ].join(' ')}
          >
            {ICONS[value]}
            <span className="sr-only">{DENSITY_LABELS[value]}</span>
          </button>
        );
      })}
    </div>
  );
}

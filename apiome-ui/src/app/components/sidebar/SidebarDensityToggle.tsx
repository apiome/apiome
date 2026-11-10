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
        'bg-subtle/80',
        'border border-border',
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
              'flex items-center justify-center w-6 h-6 rounded-xs transition-colors',
              active
                ? 'bg-surface text-accent-fg shadow-sm ring-1 ring-border'
                : 'text-fg-muted hover:text-fg',
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

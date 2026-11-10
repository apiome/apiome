'use client';

import { ReactNode } from 'react';

type Variant = 'tenant' | 'project' | 'version';

interface EntityHeaderProps {
  variant: Variant;
  title: string;
  subtitle?: string;
  description?: string;
  monogram?: string;
  meta?: { label: string; value?: ReactNode; tone?: 'neutral' | 'success' | 'brand' }[];
  actions?: ReactNode;
  badges?: ReactNode;
}

const monogramTone: Record<Variant, string> = {
  tenant:
    'bg-gradient-to-br from-sky-500/25 to-sky-500/5 text-accent-fg',
  project:
    'bg-gradient-to-br from-blue-700/25 to-blue-700/5 text-accent-fg',
  version:
    'bg-gradient-to-br from-amber-400/35 to-amber-400/10 text-honey-fg',
};

const metaTone: Record<NonNullable<EntityHeaderProps['meta']>[number]['tone'] & string, string> = {
  neutral: 'text-fg-muted',
  success: 'text-ok-fg',
  brand: 'text-accent-fg',
};

function VariantIcon({ variant }: { variant: Variant }) {
  if (variant === 'tenant') {
    return (
      <svg className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4" />
      </svg>
    );
  }
  if (variant === 'project') {
    return (
      <svg className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    );
  }
  return (
    <svg className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a3 3 0 11-6 0 3 3 0 016 0zM6 21l5-5m0 0l5 5m-5-5V3" />
    </svg>
  );
}

export function EntityHeader({
  variant,
  title,
  subtitle,
  description,
  monogram,
  meta,
  actions,
  badges,
}: EntityHeaderProps) {
  return (
    <section className="rounded-lg border border-border bg-surface p-5 shadow-xs sm:p-6">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-4 min-w-0">
          <div
            className={`hex flex h-14 w-14 shrink-0 items-center justify-center ${monogramTone[variant]}`}
            aria-hidden="true"
          >
            {monogram ? (
              <span className="text-xl font-semibold tabular-nums">{monogram}</span>
            ) : (
              <VariantIcon variant={variant} />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className="truncate text-[1.5rem] font-semibold tracking-tight text-fg">
                {title}
              </h1>
              {badges}
            </div>
            {subtitle && (
              <p className="mt-1 font-mono text-xs text-fg-muted">{subtitle}</p>
            )}
            {description && (
              <p className="mt-2 max-w-2xl text-base leading-relaxed text-fg-muted">
                {description}
              </p>
            )}
          </div>
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2 sm:flex-nowrap">{actions}</div>
        )}
      </div>

      {meta && meta.length > 0 && (
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-border pt-4 sm:grid-cols-4">
          {meta.map((m, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              <dt className="text-2xs font-medium uppercase tracking-wider text-fg-muted">
                {m.label}
              </dt>
              <dd className={`text-base font-medium ${metaTone[m.tone ?? 'neutral']}`}>
                {m.value ?? '—'}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

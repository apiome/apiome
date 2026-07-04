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
    'bg-gradient-to-br from-sky-500/25 to-sky-500/5 text-sky-700 dark:text-sky-300',
  project:
    'bg-gradient-to-br from-blue-700/25 to-blue-700/5 text-blue-800 dark:text-blue-300',
  version:
    'bg-gradient-to-br from-amber-400/35 to-amber-400/10 text-amber-700 dark:text-amber-300',
};

const metaTone: Record<NonNullable<EntityHeaderProps['meta']>[number]['tone'] & string, string> = {
  neutral: 'text-zinc-700 dark:text-zinc-200',
  success: 'text-emerald-700 dark:text-emerald-400',
  brand: 'text-[var(--brand-soft-text)]',
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
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-xs dark:border-zinc-800 dark:bg-zinc-950 sm:p-6">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-4 min-w-0">
          <div
            className={`hex flex h-14 w-14 shrink-0 items-center justify-center ${monogramTone[variant]}`}
            aria-hidden="true"
          >
            {monogram ? (
              <span className="text-lg font-semibold tabular-nums">{monogram}</span>
            ) : (
              <VariantIcon variant={variant} />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className="truncate text-[1.5rem] font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                {title}
              </h1>
              {badges}
            </div>
            {subtitle && (
              <p className="mt-1 font-mono text-xs text-zinc-500 dark:text-zinc-400">{subtitle}</p>
            )}
            {description && (
              <p className="mt-2 max-w-2xl text-[14px] leading-relaxed text-zinc-600 dark:text-zinc-400">
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
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-zinc-100 pt-4 sm:grid-cols-4 dark:border-zinc-800/80">
          {meta.map((m, i) => (
            <div key={i} className="flex flex-col gap-0.5">
              <dt className="text-[11px] font-medium uppercase tracking-wider text-zinc-500 dark:text-zinc-500">
                {m.label}
              </dt>
              <dd className={`text-sm font-medium ${metaTone[m.tone ?? 'neutral']}`}>
                {m.value ?? '—'}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

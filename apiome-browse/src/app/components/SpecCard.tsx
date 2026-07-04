'use client';

import Link from 'next/link';

type Variant = 'tenant' | 'project' | 'version';

interface SpecCardProps {
  variant: Variant;
  href: string;
  title: string;
  subtitle?: string;
  description?: string;
  meta?: { label: string; value?: string }[];
  badge?: { label: string; tone?: 'neutral' | 'success' | 'brand' };
  monogram?: string;
}

const monogramTone: Record<Variant, string> = {
  tenant:
    'bg-gradient-to-br from-sky-500/25 to-sky-500/5 text-sky-700 dark:text-sky-300',
  project:
    'bg-gradient-to-br from-blue-700/25 to-blue-700/5 text-blue-800 dark:text-blue-300',
  version:
    'bg-gradient-to-br from-amber-400/35 to-amber-400/10 text-amber-700 dark:text-amber-300',
};

const badgeTone: Record<NonNullable<SpecCardProps['badge']>['tone'] & string, string> = {
  neutral: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
  success: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  brand: 'bg-[var(--brand-soft)] text-[var(--brand-soft-text)]',
};

function VariantIcon({ variant }: { variant: Variant }) {
  if (variant === 'tenant') {
    return (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4" />
      </svg>
    );
  }
  if (variant === 'project') {
    return (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    );
  }
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a3 3 0 11-6 0 3 3 0 016 0zM6 21l5-5m0 0l5 5m-5-5V3" />
    </svg>
  );
}

export function SpecCard({
  variant,
  href,
  title,
  subtitle,
  description,
  meta,
  badge,
  monogram,
}: SpecCardProps) {
  return (
    <Link
      href={href}
      className="group flex h-full flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md dark:hover:border-sky-800 focus-visible:outline-none dark:border-zinc-800 dark:bg-zinc-950"
    >
      <div className="flex items-start justify-between gap-3">
        <div className={`hex flex h-10 w-10 shrink-0 items-center justify-center ${monogramTone[variant]}`}>
          {monogram ? (
            <span className="text-sm font-semibold tabular-nums">{monogram}</span>
          ) : (
            <VariantIcon variant={variant} />
          )}
        </div>
        {badge && (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
              badgeTone[badge.tone ?? 'neutral']
            }`}
          >
            {badge.label}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <h3 className="truncate text-[15px] font-semibold text-zinc-900 transition-colors group-hover:text-[var(--brand)] dark:text-zinc-50">
            {title}
          </h3>
          {subtitle && (
            <span className="truncate text-xs text-zinc-500 dark:text-zinc-400">{subtitle}</span>
          )}
        </div>
        {description && (
          <p className="mt-1 line-clamp-2 text-[13px] leading-snug text-zinc-600 dark:text-zinc-400">
            {description}
          </p>
        )}
      </div>

      {meta && meta.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-zinc-100 pt-2.5 text-[11px] text-zinc-500 dark:border-zinc-800/80 dark:text-zinc-400">
          {meta.map((m, i) => (
            <span key={i} className="flex items-center gap-1">
              <span className="font-medium text-zinc-600 dark:text-zinc-300">{m.label}</span>
              {m.value && <span>{m.value}</span>}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}

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
    'bg-gradient-to-br from-sky-500/25 to-sky-500/5 text-accent-fg',
  project:
    'bg-gradient-to-br from-blue-700/25 to-blue-700/5 text-accent-fg',
  version:
    'bg-gradient-to-br from-amber-400/35 to-amber-400/10 text-honey-fg',
};

const badgeTone: Record<NonNullable<SpecCardProps['badge']>['tone'] & string, string> = {
  neutral: 'bg-subtle text-fg-muted',
  success: 'bg-ok-soft text-ok-fg',
  brand: 'bg-accent-soft text-accent-fg',
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
      className="group flex h-full flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-md focus-visible:outline-none"
    >
      <div className="flex items-start justify-between gap-3">
        <div className={`hex flex h-10 w-10 shrink-0 items-center justify-center ${monogramTone[variant]}`}>
          {monogram ? (
            <span className="text-base font-semibold tabular-nums">{monogram}</span>
          ) : (
            <VariantIcon variant={variant} />
          )}
        </div>
        {badge && (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium ${
              badgeTone[badge.tone ?? 'neutral']
            }`}
          >
            {badge.label}
          </span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <h3 className="truncate text-lg font-semibold text-fg transition-colors group-hover:text-accent-fg">
            {title}
          </h3>
          {subtitle && (
            <span className="truncate text-xs text-fg-muted">{subtitle}</span>
          )}
        </div>
        {description && (
          <p className="mt-1 line-clamp-2 text-sm leading-snug text-fg-muted">
            {description}
          </p>
        )}
      </div>

      {meta && meta.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2.5 text-2xs text-fg-muted">
          {meta.map((m, i) => (
            <span key={i} className="flex items-center gap-1">
              <span className="font-medium text-fg-muted">{m.label}</span>
              {m.value && <span>{m.value}</span>}
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}

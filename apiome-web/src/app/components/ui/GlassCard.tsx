import { cn } from '@/lib/utils';
import * as React from 'react';

type Tone =
  | 'blue'
  | 'emerald'
  | 'purple'
  | 'orange'
  | 'indigo'
  | 'sky'
  | 'rose'
  | 'cyan'
  | 'violet'
  | 'amber'
  | 'pink'
  | 'red'
  | 'teal'
  | 'green';

const TONE_CHIP: Record<Tone, string> = {
  blue:    'bg-blue-100 text-blue-600 dark:bg-blue-950/60 dark:text-blue-300',
  emerald: 'bg-emerald-100 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-300',
  purple:  'bg-purple-100 text-purple-600 dark:bg-purple-950/60 dark:text-purple-300',
  orange:  'bg-orange-100 text-orange-600 dark:bg-orange-950/60 dark:text-orange-300',
  indigo:  'bg-indigo-100 text-indigo-600 dark:bg-indigo-950/60 dark:text-indigo-300',
  sky:     'bg-sky-100 text-sky-600 dark:bg-sky-950/60 dark:text-sky-300',
  rose:    'bg-rose-100 text-rose-600 dark:bg-rose-950/60 dark:text-rose-300',
  cyan:    'bg-cyan-100 text-cyan-600 dark:bg-cyan-950/60 dark:text-cyan-300',
  violet:  'bg-violet-100 text-violet-600 dark:bg-violet-950/60 dark:text-violet-300',
  amber:   'bg-amber-100 text-amber-600 dark:bg-amber-950/60 dark:text-amber-300',
  pink:    'bg-pink-100 text-pink-600 dark:bg-pink-950/60 dark:text-pink-300',
  red:     'bg-red-100 text-red-600 dark:bg-red-950/60 dark:text-red-300',
  teal:    'bg-teal-100 text-teal-600 dark:bg-teal-950/60 dark:text-teal-300',
  green:   'bg-green-100 text-green-600 dark:bg-green-950/60 dark:text-green-300',
};

type GlassCardProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: 'default' | 'strong';
  interactive?: boolean;
};

export function GlassCard({
  className,
  variant = 'default',
  interactive = true,
  ...props
}: GlassCardProps) {
  return (
    <div
      className={cn(
        'relative rounded-2xl',
        variant === 'strong' ? 'glass-strong' : 'glass',
        interactive && 'gradient-border transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_20px_60px_-15px_rgba(37,99,235,0.25)] dark:hover:shadow-[0_20px_60px_-15px_rgba(96,165,250,0.35)]',
        className,
      )}
      {...props}
    />
  );
}

export function ToneChip({
  tone,
  className,
  children,
}: {
  tone: Tone;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        'inline-flex h-11 w-11 items-center justify-center rounded-xl ring-1 ring-inset ring-white/40 dark:ring-white/10',
        TONE_CHIP[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}

export type { Tone };

import { cn } from '@/lib/utils';

type AuroraProps = {
  className?: string;
  variant?: 'default' | 'subtle';
};

/**
 * Layered mesh-gradient background for hero sections.
 * - Blurred, drifting blobs behind a subtle grid overlay.
 * - Respects prefers-reduced-motion via globals.css guard.
 * - Positioned absolute; parent must be `relative overflow-hidden`.
 */
export function Aurora({ className, variant = 'default' }: AuroraProps) {
  const blobOpacity = variant === 'subtle' ? 'opacity-60' : 'opacity-100';

  return (
    <div
      aria-hidden
      className={cn('pointer-events-none absolute inset-0 -z-10 overflow-hidden', className)}
    >
      {/* Mesh blobs */}
      <div className={cn('absolute inset-0', blobOpacity)}>
        <div
          className="absolute -left-20 -top-32 h-[38rem] w-[38rem] rounded-full blur-3xl"
          style={{
            background: 'radial-gradient(circle at 30% 30%, var(--blob-1), transparent 60%)',
            animation: 'aurora-drift 18s ease-in-out infinite',
          }}
        />
        <div
          className="absolute right-[-10%] top-20 h-[34rem] w-[34rem] rounded-full blur-3xl"
          style={{
            background: 'radial-gradient(circle at 60% 40%, var(--blob-2), transparent 60%)',
            animation: 'aurora-drift 22s ease-in-out -6s infinite',
          }}
        />
        <div
          className="absolute left-1/3 top-[55%] h-[28rem] w-[28rem] rounded-full blur-3xl"
          style={{
            background: 'radial-gradient(circle at 50% 50%, var(--blob-3), transparent 65%)',
            animation: 'aurora-drift 26s ease-in-out -12s infinite',
          }}
        />
      </div>

      {/* Faint honeycomb overlay on top of the blobs */}
      <svg
        className="absolute inset-0 h-full w-full text-zinc-600/[0.05] dark:text-zinc-400/[0.04]"
        aria-hidden
      >
        <defs>
          <pattern
            id="aurora-hex"
            width="28"
            height="49"
            patternUnits="userSpaceOnUse"
            patternTransform="scale(2.6)"
          >
            <path
              d="M13.99 9.25l13 7.5v15l-13 7.5L1 31.75v-15l12.99-7.5zM3 17.9v12.7l10.99 6.34 11-6.35V17.9l-11-6.34L3 17.9zM0 15l12.98-7.5V0h-2v6.35L0 12.69v2.3zm0 18.5L12.98 41v8h-2v-6.85L0 35.81v-2.3zM15 0v7.5L27.99 15H28v-2.31h-.01L17 6.35V0h-2zm0 49v-8l12.99-7.5H28v2.31h-.01L17 42.15V49h-2z"
              fill="currentColor"
              fillRule="evenodd"
            />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#aurora-hex)" />
      </svg>

      {/* Radial vignette fade so content reads clearly */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_20%,var(--background)_85%)]" />
    </div>
  );
}

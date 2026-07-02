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

      {/* Crisp grid overlay on top of the blobs */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808014_1px,transparent_1px),linear-gradient(to_bottom,#80808014_1px,transparent_1px)] bg-[size:28px_28px]" />

      {/* Radial vignette fade so content reads clearly */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_20%,var(--background)_85%)]" />
    </div>
  );
}

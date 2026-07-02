import { cn } from "@/lib/utils";

/**
 * Pure-CSS infinite marquee. Renders the children twice so the loop is seamless;
 * pauses on hover and freezes under prefers-reduced-motion (handled in CSS).
 */
export function Marquee({
  children,
  className,
  reverse = false,
  duration = 32,
}: {
  children: React.ReactNode;
  className?: string;
  reverse?: boolean;
  duration?: number;
}) {
  return (
    <div
      className={cn("marquee-mask group relative flex overflow-hidden", className)}
    >
      {[0, 1].map((dup) => (
        <div
          key={dup}
          aria-hidden={dup === 1}
          className="flex shrink-0 items-center gap-12 pr-12 will-change-transform group-hover:[animation-play-state:paused]"
          style={{
            animation: `marquee-x ${duration}s linear infinite`,
            animationDirection: reverse ? "reverse" : "normal",
          }}
        >
          {children}
        </div>
      ))}
    </div>
  );
}

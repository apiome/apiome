import Image from "next/image";
import { cn } from "@/lib/utils";

type BrowserFrameProps = {
  src: string;
  alt: string;
  /** Optional URL-bar label shown in the faux browser chrome. */
  label?: string;
  /** Prioritise loading (use for the hero image only). */
  priority?: boolean;
  className?: string;
};

/**
 * Wraps a product screenshot in a lightweight browser-chrome frame so the
 * marketing walkthrough reads as authentic UI rather than a bare image.
 */
export function BrowserFrame({
  src,
  alt,
  label = "app.apiome.app",
  priority = false,
  className,
}: BrowserFrameProps) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-2xl border border-zinc-200/80 bg-white/80 shadow-[0_30px_80px_-30px_rgba(37,99,235,0.35)] backdrop-blur dark:border-zinc-800/80 dark:bg-zinc-900/70",
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-zinc-200/80 bg-zinc-50/80 px-4 py-2.5 dark:border-zinc-800/80 dark:bg-zinc-900/80">
        <span className="h-3 w-3 rounded-full bg-red-400/80" aria-hidden />
        <span className="h-3 w-3 rounded-full bg-amber-400/80" aria-hidden />
        <span className="h-3 w-3 rounded-full bg-emerald-400/80" aria-hidden />
        <div className="ml-3 hidden flex-1 sm:block">
          <div className="inline-flex max-w-full items-center rounded-md bg-white/70 px-3 py-1 text-xs font-medium text-zinc-500 ring-1 ring-inset ring-zinc-200/80 dark:bg-zinc-950/60 dark:text-zinc-400 dark:ring-zinc-800/80">
            {label}
          </div>
        </div>
      </div>
      <Image
        src={src}
        alt={alt}
        width={1440}
        height={900}
        priority={priority}
        sizes="(min-width: 1024px) 720px, 100vw"
        className="h-auto w-full"
      />
    </div>
  );
}

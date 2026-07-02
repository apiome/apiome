"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const ConstellationScene = dynamic(() => import("./ConstellationScene"), {
  ssr: false,
});

/**
 * Mounts the WebGL constellation only on the client, fading it in once the
 * canvas is ready so there is never a hard pop. Sits behind the hero content.
 */
export function HeroConstellation({ className }: { className?: string }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Defer a frame so the heavy WebGL init doesn't block first paint.
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 -z-10 transition-opacity duration-[1400ms] ease-out",
        ready ? "opacity-100" : "opacity-0",
        className,
      )}
    >
      {ready && <ConstellationScene className="h-full w-full" />}
    </div>
  );
}

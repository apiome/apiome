"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const HiveScene = dynamic(() => import("./HiveScene"), {
  ssr: false,
});

/**
 * Mounts the honeycomb canvas only on the client, fading it in once ready so
 * there is never a hard pop. Sits behind the hero content, masked so the hive
 * dissolves toward the edges instead of ending in a hard line.
 */
export function HeroHive({ className }: { className?: string }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Defer a frame so canvas init doesn't block first paint.
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 -z-10 transition-opacity duration-[1400ms] ease-out",
        "[mask-image:radial-gradient(ellipse_115%_95%_at_50%_42%,#000_38%,transparent_80%)]",
        ready ? "opacity-100" : "opacity-0",
        className,
      )}
    >
      {ready && <HiveScene className="h-full w-full" />}
    </div>
  );
}

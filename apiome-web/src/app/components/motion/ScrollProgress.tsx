"use client";

import { useEffect, useRef } from "react";
import { gsap, ScrollTrigger, prefersReducedMotion } from "./gsap";

/**
 * A thin gradient progress bar pinned to the top of the viewport that tracks
 * how far the reader has scrolled through the page.
 */
export function ScrollProgress() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion()) return;
    gsap.set(el, { scaleX: 0, transformOrigin: "left center" });
    const st = ScrollTrigger.create({
      start: 0,
      end: "max",
      onUpdate: (self) => gsap.set(el, { scaleX: self.progress }),
    });
    return () => st.kill();
  }, []);

  return (
    <div
      aria-hidden
      ref={ref}
      className="fixed inset-x-0 top-0 z-[150] h-[3px] origin-left bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500"
    />
  );
}

"use client";

import { useEffect, useRef } from "react";
import { gsap, prefersReducedMotion } from "./gsap";

/**
 * Wraps an interactive element so it leans toward the cursor while hovered and
 * springs back on leave — the "magnetic button" effect. Renders an inline-block
 * wrapper; pass `block` for full-width children.
 */
export function Magnetic({
  children,
  strength = 0.4,
  className,
  block = false,
}: {
  children: React.ReactNode;
  strength?: number;
  className?: string;
  block?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion()) return;
    const setX = gsap.quickTo(el, "x", { duration: 0.5, ease: "power3.out" });
    const setY = gsap.quickTo(el, "y", { duration: 0.5, ease: "power3.out" });

    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const x = e.clientX - (rect.left + rect.width / 2);
      const y = e.clientY - (rect.top + rect.height / 2);
      setX(x * strength);
      setY(y * strength);
    };
    const onLeave = () => {
      setX(0);
      setY(0);
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
    };
  }, [strength]);

  return (
    <div
      ref={ref}
      className={className}
      style={{ display: block ? "block" : "inline-block", willChange: "transform" }}
    >
      {children}
    </div>
  );
}

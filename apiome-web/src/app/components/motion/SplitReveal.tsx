"use client";

import { Fragment, useEffect, useRef } from "react";
import { gsap, prefersReducedMotion } from "./gsap";
import { cn } from "@/lib/utils";

type SplitRevealProps = {
  /** Plain text to split into word-masked lines. */
  text: string;
  className?: string;
  /** ClassName applied to every word's visible inner span. */
  wordClassName?: string;
  as?: "span" | "div" | "h1" | "h2" | "p";
  delay?: number;
  stagger?: number;
  duration?: number;
  /** Animate as soon as mounted (hero) instead of on scroll into view. */
  immediate?: boolean;
};

/**
 * Word-by-word mask reveal. Each word rides up from behind a clipped edge with
 * a GSAP stagger — the signature "kinetic type" entrance. Falls back to plain
 * static text under prefers-reduced-motion.
 */
export function SplitReveal({
  text,
  className,
  wordClassName,
  as = "span",
  delay = 0,
  stagger = 0.06,
  duration = 0.9,
  immediate = false,
}: SplitRevealProps) {
  const ref = useRef<HTMLElement>(null);
  const Tag = as as React.ElementType;
  const words = text.split(" ");

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReducedMotion()) return;

    const targets = el.querySelectorAll<HTMLElement>("[data-word-inner]");
    // 140 (not 115) so words start fully below the deepened mask window.
    gsap.set(targets, { yPercent: 140 });

    const animate = () =>
      gsap.to(targets, {
        yPercent: 0,
        duration,
        delay,
        stagger,
        ease: "power4.out",
        overwrite: true,
      });

    if (immediate) {
      const tween = animate();
      return () => {
        tween.kill();
      };
    }

    const st = gsap.to(targets, {
      yPercent: 0,
      duration,
      stagger,
      ease: "power4.out",
      paused: true,
      scrollTrigger: {
        trigger: el,
        start: "top 85%",
        once: true,
      },
    });
    return () => {
      st.scrollTrigger?.kill();
      st.kill();
    };
  }, [delay, duration, stagger, immediate]);

  if (prefersReducedMotion()) {
    return (
      <Tag className={className}>
        <span className={wordClassName}>{text}</span>
      </Tag>
    );
  }

  return (
    <Tag ref={ref} className={className} aria-label={text}>
      {words.map((word, i) => (
        <Fragment key={`${word}-${i}`}>
          <span
            aria-hidden
            className="inline-block overflow-hidden align-top"
            // Deep mask window so italic/serif descenders (e.g. the "y" in
            // "Visually") aren't clipped; the negative margin cancels the
            // extra padding so line spacing stays unchanged.
            style={{ paddingBottom: "0.32em", marginBottom: "-0.2em" }}
          >
            <span
              data-word-inner
              className={cn("inline-block will-change-transform", wordClassName)}
            >
              {word}
            </span>
          </span>
          {i < words.length - 1 ? " " : ""}
        </Fragment>
      ))}
    </Tag>
  );
}

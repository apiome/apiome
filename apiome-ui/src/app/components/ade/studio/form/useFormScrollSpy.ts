'use client';

import { useEffect, useRef, useState } from 'react';

export interface UseFormScrollSpyOptions {
  /** Ordered list of section ids that participate in the spy. */
  sectionIds: string[];
  /** The scroll container element that wraps the sections. */
  containerRef: React.RefObject<HTMLElement | null>;
  /**
   * Px offset from the top of the container at which a section is considered
   * "active". Tunes where the active indicator flips.
   */
  rootMarginTop?: number;
  /** Disable the spy. */
  disabled?: boolean;
}

/**
 * IntersectionObserver-backed scroll spy. Returns the id of the section that
 * is currently dominant in the scroll container. Falls back to the first
 * section id before any intersection fires.
 */
export function useFormScrollSpy({
  sectionIds,
  containerRef,
  rootMarginTop = 80,
  disabled = false,
}: UseFormScrollSpyOptions) {
  const [activeId, setActiveId] = useState<string>(sectionIds[0] || '');
  const visibilityRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    if (disabled) return;
    const container = containerRef.current;
    if (!container) return;
    if (sectionIds.length === 0) return;

    visibilityRef.current = new Map(sectionIds.map((id) => [id, 0]));

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = (entry.target as HTMLElement).dataset.sectionId;
          if (!id) continue;
          visibilityRef.current.set(id, entry.intersectionRatio);
        }
        // Pick the section with the highest visible ratio; on tie keep the
        // earliest section in document order.
        let bestId = sectionIds[0];
        let bestRatio = -1;
        for (const id of sectionIds) {
          const ratio = visibilityRef.current.get(id) ?? 0;
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestId = id;
          }
        }
        if (bestRatio > 0) setActiveId(bestId);
      },
      {
        root: container,
        rootMargin: `-${rootMarginTop}px 0px -55% 0px`,
        threshold: [0, 0.1, 0.25, 0.5, 0.75, 1],
      },
    );

    const nodes: HTMLElement[] = [];
    for (const id of sectionIds) {
      const el = container.querySelector<HTMLElement>(`[data-section-id="${id}"]`);
      if (el) {
        observer.observe(el);
        nodes.push(el);
      }
    }

    return () => {
      for (const el of nodes) observer.unobserve(el);
      observer.disconnect();
    };
  }, [sectionIds, containerRef, rootMarginTop, disabled]);

  return { activeId, setActiveId } as const;
}

/**
 * Smooth-scroll a section into view inside the given scroll container.
 */
export function scrollToSection(
  container: HTMLElement | null,
  sectionId: string,
  offsetTop = 16,
) {
  if (!container) return;
  const target = container.querySelector<HTMLElement>(`[data-section-id="${sectionId}"]`);
  if (!target) return;
  const top = target.offsetTop - offsetTop;
  container.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
}

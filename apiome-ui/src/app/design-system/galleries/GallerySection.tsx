import * as React from 'react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/app/components/ui';

/**
 * The two building blocks every `/design-system` gallery section is drawn with (HIVE-2.1,
 * #5280; shared since HIVE-10.5, #5341).
 */

/** Props for {@link Section}. */
export interface SectionProps {
  /** The anchor the page's contents list links to. Listed in `./sections.ts`. */
  id: string;
  /** The section's title. */
  title: string;
  /** One sentence on what the section shows. */
  description: string;
  /** The specimens. */
  children: React.ReactNode;
}

/**
 * One titled block of the gallery: a flat card with a title, a description and the specimens.
 *
 * @param props See {@link SectionProps}.
 * @returns The anchored section.
 */
export function Section({ id, title, description, children }: SectionProps) {
  return (
    <section id={id} className="scroll-mt-24">
      <Card variant="flat">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">{children}</CardContent>
      </Card>
    </section>
  );
}

/**
 * A tinted well the specimens sit in, so their own surface colour is visible.
 *
 * @param props The specimens, and extra classes for the well.
 * @returns The well.
 */
export function Demo({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={
        'flex flex-wrap items-center gap-2.5 rounded-md bg-canvas p-4 shadow-[inset_0_0_0_1px_var(--border)] ' +
        (className ?? '')
      }
    >
      {children}
    </div>
  );
}

/**
 * A small caps caption above a group of specimens inside a section.
 *
 * @param props The caption text.
 * @returns The caption.
 */
export function SpecimenLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-2xs font-semibold uppercase tracking-[0.06em] text-fg-muted">
      {children}
    </div>
  );
}

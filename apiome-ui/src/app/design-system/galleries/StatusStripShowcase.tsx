'use client';

/**
 * The §Status strip specimens of the gallery (HIVE-11.1, #5597).
 *
 * The production counterpart of annotation 3 of
 * `docs/mockups/proposals/versions-status-strip.html`: a three-status strip (the Versions
 * page's compatible · what's new · deprecated), a three-status strip led by `danger`, one
 * single-status strip per tone, and the loading state. No specimen passes a `storageKey`, so
 * the gallery always opens on the severity default.
 */

import * as React from 'react';
import { ArrowUpRight, ShieldCheck, Sparkles, Sunset } from 'lucide-react';

import {
  Button,
  StatusStrip,
  type StatusStripItem,
  type StatusStripTone,
} from '@/app/components/ui';
import { SpecimenLabel } from './GallerySection';

/** The Versions page's three statuses — `warn` opens first. */
const VERSIONS_ITEMS: readonly StatusStripItem[] = [
  {
    id: 'compat',
    tone: 'ok',
    icon: ShieldCheck,
    label: 'Compatible',
    detail: 'v2.3.0 → v2.3.1',
    title: 'Compatible.',
    body: 'Parent → head check recorded 2 h ago: 3 additive changes and no breaking changes.',
    actions: (
      <Button size="sm" variant="outline">
        View report
      </Button>
    ),
  },
  {
    id: 'new',
    tone: 'accent',
    icon: Sparkles,
    label: 'What’s new',
    detail: 'v2.4.0 draft',
    title: 'What’s new in v2.4.0 (draft).',
    body: 'Refund reasons on POST /refunds, payout webhook events, Idempotency-Key on all writes.',
    actions: (
      <Button size="sm" variant="outline">
        Open changes
      </Button>
    ),
  },
  {
    id: 'sunset',
    tone: 'warn',
    icon: Sunset,
    label: 'v2.2.0 deprecated',
    detail: '· sunset 30 Sep',
    title: 'v2.2.0 is deprecated — sunset 30 Sep 2026 00:00 UTC.',
    body: 'Successor v2.3.1. Migrate to /payment-intents before sunset.',
    actions: (
      <>
        <Button size="sm" variant="outline">
          Sunset timeline
        </Button>
        <Button size="sm" variant="outline">
          Migration guide
          <ArrowUpRight aria-hidden />
        </Button>
      </>
    ),
  },
];

/** A strip led by `danger`, so the most severe tone is seen opening first. */
const DANGER_ITEMS: readonly StatusStripItem[] = [
  {
    id: 'lint',
    tone: 'ok',
    label: 'Lint clean',
    title: 'Lint clean.',
    body: 'No findings against the workspace style guide.',
  },
  {
    id: 'ahead',
    tone: 'accent',
    label: 'Server is ahead',
    detail: '2 commits',
    title: 'The server is 2 commits ahead.',
    body: 'Pull before you push, or your push will be rejected.',
  },
  {
    id: 'breaking',
    tone: 'danger',
    label: 'Breaking change',
    detail: '1 removed field',
    title: 'Breaking change.',
    body: 'Order.total was removed; 4 consumers still read it.',
    actions: (
      <Button size="sm" variant="outline">
        View consumers
      </Button>
    ),
  },
];

/** One sentence per tone for the single-status specimens. */
const SINGLE_COPY: Readonly<Record<StatusStripTone, { label: string; title: string }>> = {
  ok: { label: 'Compatible', title: 'No breaking changes since v2.3.0.' },
  accent: { label: 'What’s new', title: 'v2.4.0 draft adds payout webhook events.' },
  warn: { label: 'Deprecated', title: 'v2.2.0 sunsets on 30 Sep 2026.' },
  danger: { label: 'Breaking change', title: 'Order.total was removed.' },
};

/** The tones, in the order the specimens show them. */
const TONES: readonly StatusStripTone[] = ['ok', 'accent', 'warn', 'danger'];

/**
 * Every state of the strip: three statuses, one status per tone, and loading.
 *
 * @returns The specimens.
 */
export function StatusStripShowcase() {
  return (
    <div className="flex flex-col gap-4">
      <SpecimenLabel>Three statuses — warn opens first</SpecimenLabel>
      <StatusStrip aria-label="Project status" items={VERSIONS_ITEMS} />

      <SpecimenLabel>Three statuses — danger opens first</SpecimenLabel>
      <StatusStrip aria-label="Version status" items={DANGER_ITEMS} />

      <SpecimenLabel>One status — already open, no Collapse</SpecimenLabel>
      {TONES.map((tone) => (
        <StatusStrip
          key={tone}
          aria-label={`Single ${tone} status`}
          items={[{ id: tone, tone, ...SINGLE_COPY[tone] }]}
        />
      ))}

      <SpecimenLabel>Loading</SpecimenLabel>
      <StatusStrip aria-label="Project status" items={[]} loading />
    </div>
  );
}

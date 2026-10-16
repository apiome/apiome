'use client';

/**
 * The §Facts line & callout specimens of the gallery (HIVE-11.5, #5601).
 *
 * The production counterpart of annotations 2 and 4 of
 * `docs/mockups/proposals/catalog-quiet.html`: a facts line over a revealable stat grid, the
 * empty ("0 items") and loading lines, an eight-fact line that has to wrap, and the
 * first-visit callout with a **Show again** control — without it, pressing **Got it** here
 * would hide the specimen on this device for good.
 */

import * as React from 'react';
import { FolderOpen, Gauge, Library } from 'lucide-react';

import { clearSeen } from '@lib/seen';
import { Button, DismissibleCallout, FactsLine, type FactsLineFact } from '@/app/components/ui';
import { Stat, StatGrid } from '@/app/components/ui/metrics';
import { SpecimenLabel } from './GallerySection';

/** The catalog's four stats, as one line. */
const CATALOG_FACTS: readonly FactsLineFact[] = [
  { id: 'items', value: 3, label: 'items' },
  { id: 'formats', value: 3, label: 'formats', formats: ['graphql', 'protobuf', 'asyncapi'] },
  { id: 'quality', label: 'avg quality', value: 'B · 83', labelFirst: true },
  { id: 'converted', value: 1, label: 'converted to OpenAPI' },
  { id: 'gone', label: '1 deleted · 1 disabled', muted: true },
];

/** Eight facts — the widest line the quiet pass plans for; it wraps instead of scrolling. */
const WIDE_FACTS: readonly FactsLineFact[] = [
  { id: 'repos', value: 12, label: 'repositories' },
  { id: 'linked', value: 9, label: 'linked' },
  { id: 'stale', value: 1, label: 'stale' },
  { id: 'failed', value: 1, label: 'failed' },
  { id: 'specs', value: 48, label: 'specs found' },
  { id: 'imported', value: 31, label: 'imported' },
  { id: 'last', label: 'last refresh', value: '2 h ago', labelFirst: true },
  { id: 'archived', label: '3 archived', muted: true },
];

/** The id the callout specimen remembers its dismissal under. */
const CALLOUT_ID = 'design-system-callout';

/**
 * Every state of the facts line, and the first-visit callout.
 *
 * @returns The specimens.
 */
export function QuietListShowcase() {
  // Bumped by "Show again" to remount the callout after its dismissal is forgotten.
  const [calloutKey, setCalloutKey] = React.useState(0);

  return (
    <div className="flex flex-col gap-4">
      <SpecimenLabel>Facts line — Show stats reveals the grid in place</SpecimenLabel>
      <FactsLine
        page="design-system"
        facts={CATALOG_FACTS}
        stats={
          <StatGrid columns={3}>
            <Stat label="Cataloged items" icon={<Library />} value={3} footnote="2 active · 1 disabled" />
            <Stat label="Avg quality" icon={<Gauge />} value="B · 83" footnote="across 3 items" />
            <Stat label="Converted" icon={<FolderOpen />} value={1} footnote="to OpenAPI" />
          </StatGrid>
        }
      />

      <SpecimenLabel>Eight facts — wraps, never scrolls</SpecimenLabel>
      <FactsLine page="design-system-wide" facts={WIDE_FACTS} />

      <SpecimenLabel>Empty — 0 items, no toggle</SpecimenLabel>
      <FactsLine page="design-system-empty" facts={CATALOG_FACTS} stats={<span />} empty />

      <SpecimenLabel>Loading</SpecimenLabel>
      <FactsLine page="design-system-loading" facts={[]} loading />

      <SpecimenLabel>First-visit callout — Got it hides it on this device</SpecimenLabel>
      <DismissibleCallout
        key={calloutKey}
        id={CALLOUT_ID}
        reopenFrom="The Show again button below this specimen"
        onLearnMore={() => undefined}
      >
        <strong>Catalog items are non-publishable.</strong> They are cataloged, versioned, diffed
        and linted like projects; convert one to OpenAPI to publish it.
      </DismissibleCallout>
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            clearSeen(CALLOUT_ID);
            setCalloutKey((key) => key + 1);
          }}
        >
          Show again
        </Button>
      </div>
    </div>
  );
}

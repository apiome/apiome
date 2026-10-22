'use client';

/**
 * The registry's facts line (HIVE-11.8, #5604).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` annotation 2 and
 * `docs/mockups/PROPOSALS.md` finding 1. The registry tab used to open with the five-tile
 * {@link PrimitivesKpiStrip} (≈ 125 px) before the collections card; the same five numbers now
 * read as one line — `24 core system types · 12 tenant types · 5 imported schemas · 88 properties
 * bound · 3 unresolved $ref` — and the strip itself is one **Show stats** click away, revealed in
 * place and remembered per device under `hive.primitives.stats`.
 *
 * ### The unresolved chip
 *
 * The one fact that asks to be acted on — unresolved `$ref` above zero — is a `danger` chip, a
 * `<button>` that switches the screen to the Resolver tab, just as the strip's amber tile does.
 * At zero it is plain text: there is nothing for the resolver to show.
 */

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';

import { FactsLine, type FactsLineFact } from '@/app/components/ui/FactsLine';
import type { RegistryCoverageStats } from '@/app/ade/dashboard/primitives/primitivesRegistryTypes';

import PrimitivesKpiStrip from './PrimitivesKpiStrip';
import { registryFacts } from './primitivesModel';

export interface PrimitivesFactsLineProps {
  /** The coverage stats, or `null` before the first read lands. */
  stats: RegistryCoverageStats | null;
  /** True while that read is in flight. */
  loading: boolean;
  /** Switch the screen to the Resolver tab — what the unresolved chip does. */
  onOpenResolver: () => void;
}

/**
 * Render the line. See {@link PrimitivesFactsLineProps}.
 *
 * @returns The facts line, with the KPI strip behind its **Show stats** toggle.
 */
export default function PrimitivesFactsLine({
  stats,
  loading,
  onOpenResolver,
}: PrimitivesFactsLineProps) {
  const facts: FactsLineFact[] = registryFacts(stats).map((fact) =>
    fact.alert
      ? {
          id: fact.id,
          // No `value`: the figure is drawn inside the chip, so the whole fact is one target.
          label: (
            <button
              type="button"
              className="prm-facts-chip"
              onClick={onOpenResolver}
              title="Open the reference resolver"
              data-testid={`primitives-fact-${fact.id}`}
            >
              <AlertTriangle aria-hidden />
              <b>{fact.value}</b> {fact.label}
            </button>
          ),
        }
      : {
          id: fact.id,
          // The figure rides inside the label here too, so every fact carries one test hook.
          label: (
            <span data-testid={`primitives-fact-${fact.id}`}>
              <b>{fact.value}</b> {fact.label}
            </span>
          ),
        }
  );

  return (
    <FactsLine
      page="primitives"
      aria-label="Registry coverage"
      facts={facts}
      loading={loading || facts.length === 0}
      stats={<PrimitivesKpiStrip stats={stats} loading={loading} onOpenResolver={onOpenResolver} />}
    />
  );
}

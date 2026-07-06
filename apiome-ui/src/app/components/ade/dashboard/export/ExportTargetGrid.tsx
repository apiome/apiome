'use client';

import type { ReactNode } from 'react';
import {
  tierBadgeClass,
  tierLabel,
  type ExportTargetCard,
} from './exportTargetCatalog';

export interface ExportTargetGridProps {
  /** The renderable target cards from `exportTargetCards` (registry-driven, MFX-1.2). */
  cards: ExportTargetCard[];
  /** The currently selected target's key, or null. */
  selectedKey: string | null;
  /** Select a target card; unavailable cards never fire this (the button is disabled). */
  onSelect: (card: ExportTargetCard) => void;
  /** Optional heading block rendered above the grid (e.g. the step's title + subtitle). */
  heading?: ReactNode;
  /**
   * Whether to render the selected-target fidelity headline below the grid (tier + preserved-%).
   * Defaults to true.
   */
  showHeadline?: boolean;
}

/**
 * ExportTargetGrid — the registry-driven target-card grid shared by the ExportDialog (MFX-6.1,
 * #3855) and the Export Studio (MFX-41.1, #4348).
 *
 * Every registered emitter from `GET /api/export/targets` renders as a card carrying its
 * per-source fidelity badge (`lossless` / `lossy` / `types-only`, MFX-2.5) so the trade-off is
 * visible before selection. Unavailable targets (missing toolchain) render disabled and
 * unselectable. Picking a target renders the fidelity headline (tier + preserved-%) below the
 * grid. This is one component, not a fork: the dialog and the Studio's Target step both mount it,
 * so a change to the card layout or badges lands in both surfaces at once.
 */
export function ExportTargetGrid({
  cards,
  selectedKey,
  onSelect,
  heading,
  showHeadline = true,
}: ExportTargetGridProps) {
  const selected = cards.find((card) => card.key === selectedKey) ?? null;
  const fidelity = selected?.entry.fidelity ?? null;

  return (
    <>
      {heading}

      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {cards.map((card) => {
          const Icon = card.icon;
          const isSelected = card.key === selectedKey;
          return (
            <button
              key={card.key}
              type="button"
              data-testid={`export-target-${card.key}`}
              onClick={() => onSelect(card)}
              disabled={!card.available}
              title={
                card.available
                  ? card.entry.descriptor.description
                  : card.entry.descriptor.unavailable_reason || 'Unavailable in this runtime'
              }
              className={`relative rounded-lg border p-3 text-center transition ${
                isSelected
                  ? 'border-indigo-500 bg-indigo-50 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-100'
                  : card.available
                    ? 'border-gray-200 bg-white text-gray-700 hover:border-indigo-200 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-200'
                    : 'cursor-not-allowed border-gray-200 bg-gray-50 text-gray-400 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-600'
              }`}
            >
              <span
                className={`absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-semibold ${tierBadgeClass(card.entry.fidelity.tier)}`}
              >
                {tierLabel(card.entry.fidelity.tier)}
              </span>
              <Icon className="mx-auto mb-2 mt-3 h-5 w-5" aria-hidden />
              <div className="text-sm font-medium">{card.entry.descriptor.label}</div>
              <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                {card.entry.descriptor.paradigm}
                {card.entry.descriptor.multi_file ? ' · multi-file' : ''}
              </div>
            </button>
          );
        })}
      </div>

      {showHeadline && selected && fidelity && (
        <div
          data-testid="export-fidelity-headline"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700"
        >
          <div className="text-gray-700 dark:text-gray-200">
            Exporting to <strong>{selected.entry.descriptor.label}</strong>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-semibold ${tierBadgeClass(fidelity.tier)}`}
            >
              {tierLabel(fidelity.tier)}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {fidelity.preserved_percent}% preserved
            </span>
          </div>
        </div>
      )}
    </>
  );
}

export default ExportTargetGrid;

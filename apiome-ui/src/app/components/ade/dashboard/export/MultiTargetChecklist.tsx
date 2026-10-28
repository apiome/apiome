'use client';

import { Badge } from '../../../ui/Badge';
import { MAX_EXPORT_PAIRS } from './exportBatchJob';
import { tierLabel, tierTone, type ExportTargetCard } from './exportTargetCatalog';

/** Props for {@link MultiTargetChecklist}. */
export interface MultiTargetChecklistProps {
  /** The source's export targets (the same cards the single-target grid shows). */
  cards: readonly ExportTargetCard[];
  /** The ticked target keys, in the order ticked. */
  selected: readonly string[];
  /** Tick or untick one target. */
  onToggle: (key: string) => void;
}

/**
 * The Export studio's "Several targets" picker (E1-3, #6219): one checkbox per available target,
 * each with this source's fidelity badge. Two or more ticked targets continue to Verify; an
 * unavailable target cannot be ticked.
 */
export function MultiTargetChecklist({ cards, selected, onToggle }: MultiTargetChecklistProps) {
  const full = selected.length >= MAX_EXPORT_PAIRS;
  return (
    <div className="xstd-stack xstd-stack--tight" data-testid="export-studio-multi-targets">
      <div>
        <div className="xstd-source__name">Choose two or more targets</div>
        <p className="xstd-quiet" role="status">
          {selected.length === 0
            ? 'Nothing ticked yet.'
            : `${selected.length} target${selected.length === 1 ? '' : 's'} ticked${selected.length < 2 ? ' — tick one more to continue' : ''}.`}
        </p>
      </div>
      <ul className="xstd-multi__list">
        {cards.map((card) => {
          const checked = selected.includes(card.key);
          const { fidelity, descriptor } = card.entry;
          return (
            <li key={card.key}>
              <label className="xstd-multi__row" data-testid={`export-studio-multi-target-${card.key}`}>
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!card.available || (full && !checked)}
                  onChange={() => onToggle(card.key)}
                />
                <span className="xstd-multi__name">{descriptor.label}</span>
                <Badge variant={tierTone(fidelity.tier)}>
                  {tierLabel(fidelity.tier)} · {fidelity.preserved_percent}%
                </Badge>
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

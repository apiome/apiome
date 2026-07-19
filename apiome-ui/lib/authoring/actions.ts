/**
 * Command actions and the selection bar (UXE-1.3).
 *
 * §27.2: "Tree, table and canvas selection share multiselect, bulk actions and
 * a visible selection bar." Sharing the *bar* means sharing the rule for when
 * an action is offered, when it is disabled, and — the part screens routinely
 * get wrong — why it is disabled.
 *
 * A disabled control with no explanation is a dead end, which §27.2 forbids.
 * `AuthoringCommandAction` therefore cannot be disabled without a reason: the
 * type makes `disabledReason` the only way to turn an action off.
 */

import type { AuthoringTone } from './tokens';

/** Visual weight of an action, mapped to a button treatment. */
export type AuthoringActionVariant = 'primary' | 'secondary' | 'ghost';

/** One action offered in a toolbar, selection bar or card footer. */
export type AuthoringCommandAction = {
  id: string;
  label: string;
  /** Lucide icon name, resolved on the client. */
  icon?: string;
  variant: AuthoringActionVariant;
  /** Tone for destructive or cautionary actions. Defaults to neutral. */
  tone?: AuthoringTone;
  /**
   * Keyboard shortcut hint, e.g. `⌘⏎`. Display only — the binding itself is
   * installed by the owning surface.
   */
  shortcut?: string;
  /**
   * Why the action is unavailable. Presence of this field *is* the disabled
   * state, so an action can never be greyed out without saying why.
   */
  disabledReason?: string;
  /** True when the action opens an impact sheet rather than acting at once. */
  confirms?: boolean;
};

/**
 * True when an action is currently unavailable.
 *
 * @param action - Action to test.
 */
export function isAuthoringActionDisabled(action: AuthoringCommandAction): boolean {
  return Boolean(action.disabledReason);
}

/** State of a multiselect bar. */
export type AuthoringSelectionSummary = {
  count: number;
  /** True when every selectable item is selected. */
  all: boolean;
  /** Label for the bar, e.g. `3 of 24 selected`. */
  label: string;
  /** Sentence announced when the selection changes. */
  announcement: string;
};

/**
 * Summarise a multiselect.
 *
 * The announcement names the noun as well as the count, because "3 selected"
 * heard out of context does not say three of what.
 *
 * @param selectedCount - Number of selected items.
 * @param totalCount - Number of selectable items.
 * @param noun - Singular noun for the items, e.g. `page`.
 * @returns Counts and the text to render and announce.
 */
export function summarizeAuthoringSelection(
  selectedCount: number,
  totalCount: number,
  noun: string
): AuthoringSelectionSummary {
  const plural = selectedCount === 1 ? noun : `${noun}s`;
  const all = totalCount > 0 && selectedCount === totalCount;

  return {
    count: selectedCount,
    all,
    label: `${selectedCount} of ${totalCount} selected`,
    announcement:
      selectedCount === 0
        ? `No ${noun}s selected.`
        : `${selectedCount} ${plural} selected of ${totalCount}.`,
  };
}

/**
 * Disable every bulk action when nothing is selected.
 *
 * Applied centrally so each surface does not re-derive it — and so the reason
 * shown is identical everywhere, rather than one screen saying "Select items"
 * and another saying nothing at all.
 *
 * @param actions - Bulk actions the surface offers.
 * @param selectedCount - Number of selected items.
 * @param noun - Singular noun for the items, e.g. `page`.
 * @returns The actions, disabled with a reason when the selection is empty.
 */
export function gateAuthoringBulkActions(
  actions: readonly AuthoringCommandAction[],
  selectedCount: number,
  noun: string
): AuthoringCommandAction[] {
  if (selectedCount > 0) return [...actions];
  return actions.map((action) => ({
    ...action,
    disabledReason: action.disabledReason ?? `Select at least one ${noun} first.`,
  }));
}

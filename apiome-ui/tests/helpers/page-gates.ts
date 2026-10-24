/**
 * The page-chrome rules HIVE-13.2 (#5615) gates, as pure functions over a rendered DOM.
 *
 * DESIGN.md §1.2 and §5.3 give a page header one primary action, a couple of secondaries and
 * an optional ⋯ menu; §5.4 gives a page one banner, with several statuses folded into a
 * `StatusStrip`; §10 forbids controls that lead nowhere. Nothing enforced any of it, which is
 * how Versions reached six header controls and three stacked banners before HIVE-11.2/11.3.
 *
 * These functions read *rendered* markup — the committed fixture dumps under `e2e/fixtures/`
 * and live Testing Library renders — because the rules are about what the reader sees: a
 * header assembled from conditionals cannot be counted from its source. They are used by
 * `tests/page-header-gate.test.tsx`; the source-level half (disabled buttons without a
 * reason, "Coming soon" inside a button) lives in `tests/copy-voice-gate.test.ts`.
 */

/** The limits of DESIGN.md §1.2 / §5.3 / §5.4. */
export const PAGE_GATE_LIMITS = {
  /** Primary (ink) buttons in a header's action cluster. */
  primary: 1,
  /** Every other `Button` in the cluster: outline, soft, ghost, accent, danger… */
  secondary: 2,
  /** ⋯ overflow menus in the cluster. */
  overflow: 1,
  /** Banners directly under the header, before the page's content starts. */
  banners: 1,
} as const;

/**
 * A class only the `Button` primitive's base string carries (`ui/Button.tsx`).
 *
 * The rendered markup does not say which component drew an element, so a `Button` is known by
 * its base classes. `tests/page-header-gate.test.tsx` renders every variant and fails if this
 * mark ever stops identifying them, so a change to the base string cannot silently empty the
 * count.
 */
export const BUTTON_MARK = 'active:translate-y-px';

/** The class the ink fill — `primary`, and its pre-Hive alias `default` — draws. */
export const PRIMARY_MARK = 'bg-ink';

/** `data-testid` of the header's action cluster (`shell/PageHeader.tsx`). */
const ACTIONS_TESTID = 'page-header-actions';

/** `data-testid` of the header's ⋯ trigger (`shell/PageHeaderOverflow.tsx`). */
const OVERFLOW_TESTID = 'page-header-overflow';

/** Roles that make an element a banner: `Alert` is `alert`, status bars `status`, callouts `note`. */
const BANNER_ROLES: ReadonlySet<string> = new Set(['alert', 'status', 'note']);

/** How many of each kind of control a header's action cluster holds. */
export interface HeaderActionCount {
  /** Primary (ink) `Button`s. */
  primary: number;
  /** Every other `Button`, including a `Button asChild` link. */
  secondary: number;
  /** ⋯ overflow triggers. */
  overflow: number;
  /** Native `<select>`s and `combobox` triggers, each by its label — any one fails. */
  selects: string[];
}

/** One broken rule, worded for a failure message. */
export interface PageGateViolation {
  /** Which rule: the header cap, the banner rule, or "Coming soon" inside a button. */
  rule: 'header-actions' | 'header-select' | 'banners' | 'coming-soon-button';
  /** What was found, e.g. `"3 secondary buttons (limit 2)"`. */
  detail: string;
}

/**
 * Whether an element was drawn by the `Button` primitive.
 *
 * @param element Any element.
 * @returns `true` for a `<button>` or a `Button asChild` link carrying {@link BUTTON_MARK}.
 */
export function isButtonPrimitive(element: Element): boolean {
  return element.classList.contains(BUTTON_MARK);
}

/**
 * Whether an element is a primary (ink) `Button`.
 *
 * @param element Any element.
 * @returns `true` when it is a `Button` drawn with the ink fill.
 */
export function isPrimaryButton(element: Element): boolean {
  return isButtonPrimitive(element) && element.classList.contains(PRIMARY_MARK);
}

/**
 * A short name for a control, for failure messages.
 *
 * @param element The control.
 * @returns Its `aria-label`, else its text, else its tag.
 */
function nameOf(element: Element): string {
  const label = element.getAttribute('aria-label') ?? element.textContent?.replace(/\s+/g, ' ').trim();
  return label || element.tagName.toLowerCase();
}

/**
 * Count the controls in a header's action cluster.
 *
 * Only `Button`s count against the cap — a score orb or a segmented filter in the cluster is a
 * read-out, not an action — and a control nested in another (an icon inside a link) counts
 * once, as its outer control. The ⋯ menu's rows are portalled out of the header, so they are
 * never counted; the trigger is the one thing that stands for them.
 *
 * @param header A `[data-testid="page-header"]` element.
 * @returns The counts; all zero for a header without actions.
 */
export function countHeaderActions(header: Element): HeaderActionCount {
  const count: HeaderActionCount = { primary: 0, secondary: 0, overflow: 0, selects: [] };
  const cluster = header.querySelector(`[data-testid="${ACTIONS_TESTID}"]`);
  if (!cluster) return count;

  for (const control of cluster.querySelectorAll('button, a, select, [role="combobox"]')) {
    if (control.parentElement?.closest('button, a, select, [role="combobox"]')) continue;
    if (control.tagName === 'SELECT' || control.getAttribute('role') === 'combobox') {
      count.selects.push(nameOf(control));
    } else if (control.getAttribute('data-testid') === OVERFLOW_TESTID) {
      count.overflow += 1;
    } else if (isPrimaryButton(control)) {
      count.primary += 1;
    } else if (isButtonPrimitive(control)) {
      count.secondary += 1;
    }
  }
  return count;
}

/**
 * Whether an element takes no space a reader could see.
 *
 * @param element Any element.
 * @returns `true` for `hidden`, `aria-hidden` and screen-reader-only elements.
 */
function isInvisible(element: Element): boolean {
  return (
    element.hasAttribute('hidden') ||
    element.getAttribute('aria-hidden') === 'true' ||
    element.classList.contains('sr-only')
  );
}

/**
 * Whether an element is a banner: an `Alert`, a status bar, a callout, or a `StatusStrip`.
 *
 * @param element Any element.
 * @returns `true` when the element is one banner. A `StatusStrip` is one, however many chips.
 */
function isBanner(element: Element): boolean {
  if (element.classList.contains('status-strip')) return true;
  return BANNER_ROLES.has(element.getAttribute('role') ?? '');
}

/**
 * The banners in a run of leading elements, or `null` once the run reaches content.
 *
 * A plain `div` whose every visible child is a banner (the old `versions-banners` stack) is
 * looked through, so stacking banners inside a wrapper does not hide them. Any other element —
 * a `form`, a `section`, a table — is page content, whatever it holds.
 *
 * @param element One element of the run.
 * @returns The banners it holds, `[]` for nothing visible, `null` for page content.
 */
function bannersIn(element: Element): Element[] | null {
  if (isInvisible(element)) return [];
  if (isBanner(element)) return [element];
  if (element.tagName !== 'DIV') return null;
  const children = Array.from(element.children);
  if (children.length === 0) return element.textContent?.trim() ? null : [];
  const found: Element[] = [];
  for (const child of children) {
    const inner = bannersIn(child);
    if (inner === null) return null;
    found.push(...inner);
  }
  return found;
}

/**
 * The banners directly under a page header, before the page's content starts.
 *
 * Reads the header's following siblings, then the leading children of the page's
 * `.page-body`, and stops at the first element that is page content. Banners further down the
 * page — an inline `Alert` inside a form — are not "under the header" and are not counted.
 *
 * @param header A `[data-testid="page-header"]` element.
 * @returns The banners, in order.
 */
export function leadingBanners(header: Element): Element[] {
  const found: Element[] = [];
  const run: Element[] = [];
  for (let next = header.nextElementSibling; next; next = next.nextElementSibling) {
    if (next.classList.contains('page-body')) {
      run.push(...Array.from(next.children));
      break;
    }
    run.push(next);
  }
  for (const element of run) {
    const inner = bannersIn(element);
    if (inner === null) break;
    found.push(...inner);
  }
  return found;
}

/**
 * Buttons whose text says "Coming soon".
 *
 * DESIGN.md §10: a feature that is not there yet is a fact about the page, not a control. A
 * "Coming soon" label goes on a plain element (or a disabled control's `title`), never inside
 * a button — which would be a control that leads nowhere.
 *
 * @param root A document or element to search.
 * @returns The offending buttons.
 */
export function comingSoonButtons(root: ParentNode): Element[] {
  return Array.from(root.querySelectorAll('button, [role="button"]')).filter((button) =>
    /coming soon/i.test(button.textContent ?? '')
  );
}

/**
 * Every page-gate rule a rendered page breaks.
 *
 * @param root A document or element holding zero or more page headers.
 * @returns One entry per broken rule; empty for a page that passes.
 */
export function pageGateViolations(root: ParentNode): PageGateViolation[] {
  const violations: PageGateViolation[] = [];

  for (const header of root.querySelectorAll('[data-testid="page-header"]')) {
    const count = countHeaderActions(header);
    const over: string[] = [];
    if (count.primary > PAGE_GATE_LIMITS.primary) {
      over.push(`${count.primary} primary buttons (limit ${PAGE_GATE_LIMITS.primary})`);
    }
    if (count.secondary > PAGE_GATE_LIMITS.secondary) {
      over.push(`${count.secondary} secondary buttons (limit ${PAGE_GATE_LIMITS.secondary})`);
    }
    if (count.overflow > PAGE_GATE_LIMITS.overflow) {
      over.push(`${count.overflow} overflow menus (limit ${PAGE_GATE_LIMITS.overflow})`);
    }
    if (over.length > 0) violations.push({ rule: 'header-actions', detail: over.join(', ') });
    for (const select of count.selects) {
      violations.push({ rule: 'header-select', detail: `a select in the actions slot: “${select}”` });
    }

    const banners = leadingBanners(header);
    if (banners.length > PAGE_GATE_LIMITS.banners) {
      violations.push({
        rule: 'banners',
        detail: `${banners.length} banners under the header (limit ${PAGE_GATE_LIMITS.banners}) — use a StatusStrip`,
      });
    }
  }

  for (const button of comingSoonButtons(root)) {
    violations.push({ rule: 'coming-soon-button', detail: `“Coming soon” inside a button: “${nameOf(button)}”` });
  }

  return violations;
}

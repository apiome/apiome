/** Shared layout tokens aligned with the Primitives dashboard screen.
 *  Scrolls inside the dashboard content pane (not the document / sidebar).
 *  `relative` is load-bearing: it makes the pane the containing block for absolutely
 *  positioned descendants (e.g. Tailwind `sr-only` elements deep in tall content), which
 *  otherwise anchor to the page root at their flow position and stretch the whole document. */
export const dashboardMainClass = 'relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-6';
export const dashboardContentStackClass = 'space-y-6';

export const dashboardPanelClass =
  'bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700';
export const dashboardPanelPaddedClass = `${dashboardPanelClass} p-4`;

export const dashboardTableWrapClass = `${dashboardPanelClass} overflow-hidden`;

export const dashboardTableTheadClass =
  'bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700';

export const dashboardThClass =
  'px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider';

export const dashboardThRightClass =
  'px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider';

export const dashboardTbodyClass = 'divide-y divide-gray-200 dark:divide-gray-700';

export const dashboardTrHoverClass =
  'hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors';

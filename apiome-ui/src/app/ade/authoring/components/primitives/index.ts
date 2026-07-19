/**
 * Barrel for the Authoring primitives (UXE-1.3).
 *
 * UXE-2.x workspaces import from here rather than reaching into individual
 * files, so a primitive can be split or renamed without a sweep through every
 * consuming screen.
 *
 * The rule these primitives exist to enforce: a downstream surface must not
 * fork status vocabulary or publish/rollback interaction. If a workspace needs
 * a state that is not here, the vocabulary in `@lib/authoring/*` is extended —
 * it does not grow a private variant.
 */

export { default as AuthoringActionButton } from './AuthoringActionButton';
export type { AuthoringActionButtonProps } from './AuthoringActionButton';

export { default as AuthoringAnalyticsPanel } from './AuthoringAnalyticsPanel';
export type { AuthoringAnalyticsPanelProps } from './AuthoringAnalyticsPanel';

export { default as AuthoringCheckSummary } from './AuthoringCheckSummary';
export type { AuthoringCheckSummaryProps } from './AuthoringCheckSummary';

export { default as AuthoringCitationList } from './AuthoringCitationList';
export type { AuthoringCitationListProps } from './AuthoringCitationList';

export { default as AuthoringContentTree } from './AuthoringContentTree';
export type { AuthoringContentTreeProps } from './AuthoringContentTree';

export { default as AuthoringDiffView } from './AuthoringDiffView';
export type { AuthoringDiffViewProps } from './AuthoringDiffView';

export { default as AuthoringImpactSheet } from './AuthoringImpactSheet';
export type { AuthoringImpactSheetProps } from './AuthoringImpactSheet';

export { default as AuthoringPeekDrawer } from './AuthoringPeekDrawer';
export type { AuthoringPeekDrawerProps } from './AuthoringPeekDrawer';

export { default as AuthoringProgressPhases } from './AuthoringProgressPhases';
export type { AuthoringProgressPhasesProps } from './AuthoringProgressPhases';

export { default as AuthoringProposalCard } from './AuthoringProposalCard';
export type { AuthoringProposalCardProps } from './AuthoringProposalCard';

export {
  default as AuthoringReleaseBadge,
  AuthoringEnvironmentBadge,
} from './AuthoringReleaseBadge';
export type {
  AuthoringReleaseBadgeProps,
  AuthoringEnvironmentBadgeProps,
} from './AuthoringReleaseBadge';

export { default as AuthoringSelectionBar } from './AuthoringSelectionBar';
export type { AuthoringSelectionBarProps } from './AuthoringSelectionBar';

export { default as AuthoringSplitWorkspace } from './AuthoringSplitWorkspace';
export type {
  AuthoringSplitWorkspaceProps,
  AuthoringWorkspacePane,
} from './AuthoringSplitWorkspace';

export { default as AuthoringToneBadge } from './AuthoringToneBadge';
export type { AuthoringToneBadgeProps } from './AuthoringToneBadge';

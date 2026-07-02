/**
 * Module-level ref so MigrationRuleNode can open the rule dialog when rendered
 * by React Flow (which may render nodes in a portal outside React context).
 */
export type OpenRuleDialogFn = (edgeId: string, sourceProp: string, targetProp: string) => void;

export const openRuleDialogRef: { current: OpenRuleDialogFn | null } = { current: null };

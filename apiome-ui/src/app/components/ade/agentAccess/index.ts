/**
 * The Agent access surface — AGX-3.4 (#4540).
 *
 * `/ade/dashboard/mcp/agents`: toolsets (which published operations agents may call), agent keys
 * (the credentials agents hold) and usage (what agents actually did). The page composes these;
 * the derivations they share are in {@link ./agentAccessModel}, which is pure and unit-tested, and
 * the calls they make are in {@link ./agentAccessApi}.
 */

export { default as AgentConfirmDialog } from './AgentConfirmDialog';
export type { AgentConfirmDialogProps } from './AgentConfirmDialog';

export { default as AgentKeysPanel } from './AgentKeysPanel';
export type { AgentKeysPanelProps, AgentKeyUsageState } from './AgentKeysPanel';

export { default as AgentUsagePanel } from './AgentUsagePanel';
export type { AgentUsagePanelProps } from './AgentUsagePanel';

export { default as AllowlistDialog } from './AllowlistDialog';
export type { AllowlistDialogProps } from './AllowlistDialog';

export { default as CreateAgentKeyDialog } from './CreateAgentKeyDialog';
export type { CreateAgentKeyDialogProps } from './CreateAgentKeyDialog';

export { default as EnableToolsetDialog } from './EnableToolsetDialog';
export type { EnableToolsetDialogProps } from './EnableToolsetDialog';

export { default as ToolChecklist } from './ToolChecklist';
export type { ToolChecklistProps } from './ToolChecklist';

export { default as ToolsetsPanel } from './ToolsetsPanel';
export type { ToolsetsPanelProps } from './ToolsetsPanel';

export * from './agentAccessModel';
export * from './agentAccessApi';

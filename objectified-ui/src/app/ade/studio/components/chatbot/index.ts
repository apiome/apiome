/** Barrel exports for the Studio AI chatbot building blocks (#258, #259). */

export { ChatBubble } from './ChatBubble';
export type { ChatBubbleProps } from './ChatBubble';
export { ChatCodeBlock, renderHighlighted } from './ChatCodeBlock';
export type { ChatCodeBlockProps } from './ChatCodeBlock';
export { ChatComposer } from './ChatComposer';
export type { ChatComposerProps } from './ChatComposer';
export { ChatContextChip } from './ChatContextChip';
export type { ChatContextChipProps } from './ChatContextChip';
export { ChatConversation } from './ChatConversation';
export type { ChatConversationProps } from './ChatConversation';
export { ChatTypingIndicator } from './ChatTypingIndicator';
export {
  buildChatContextPreamble,
  CHAT_CONTEXT_CLASS_CAP,
  CHAT_CONTEXT_DESCRIPTION_CHAR_CAP,
  CHAT_CONTEXT_PROPERTY_CAP,
  CHAT_CONTEXT_SCHEMA_CHAR_CAP,
  CHAT_CONTEXT_SELECTION_CAP,
  EMPTY_CHAT_STUDIO_CONTEXT,
  getSelectedClasses,
  injectChatContext,
  isChatStudioContextEmpty,
  summarizeChatStudioContext,
} from './chat-context';
export type {
  ChatStudioClass,
  ChatStudioContext,
  ChatStudioProject,
  ChatStudioProperty,
  ChatStudioVersion,
} from './chat-context';
export { ConversationHistoryPanel } from './ConversationHistoryPanel';
export type { ConversationHistoryPanelProps } from './ConversationHistoryPanel';
export { createDemoChatResponder } from './demo-responder';
export {
  detectOpenApiSpecs,
  hasOpenApiSpec,
} from './openapi-detection';
export type { DetectedOpenApiSpec } from './openapi-detection';
export {
  applyRefinementsToSpec,
  buildConversationHistoryPreamble,
  CHAT_HISTORY_EXCERPT_CHAR_CAP,
  CHAT_HISTORY_TURN_CAP,
  summarizeConversationHistory,
} from './conversation-history';
export type {
  ChatFollowUpIntent,
  ChatHistoryExcerpt,
  ChatHistorySummary,
  ChatRefinementOp,
} from './conversation-history';
export {
  buildStoredConversation,
  CHAT_HISTORY_MAX_CONVERSATIONS,
  CHAT_HISTORY_STORAGE_KEY,
  CHAT_HISTORY_TITLE_CHAR_CAP,
  createConversationStore,
  createLocalStorageConversationStorage,
  createMemoryConversationStorage,
  deriveConversationTitle,
  exportConversationToMarkdown,
  exportConversationsToMarkdown,
} from './conversation-store';
export type {
  ConversationStorage,
  ConversationStore,
  StoredConversation,
  StoredConversationScope,
} from './conversation-store';
export type { ChatFeedback, ChatMessage, ChatRole, ChatSendContext, ChatSendFn } from './types';

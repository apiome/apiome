'use client';

/**
 * Indeterminate progress bar while the assistant is generating (#523).
 * Sits under the chat toolbar so generation is visible for the whole turn,
 * including the gap before the first streamed token arrives.
 */
export function ChatBusyProgressIndicator() {
  return (
    <div
      className="shrink-0 border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900"
      data-testid="studio-ai-chat-generation-progress"
    >
      <div
        role="progressbar"
        aria-label="Chat response progress"
        aria-valuetext="Generating response"
        className="relative h-1 w-full overflow-hidden bg-gray-200 dark:bg-gray-700"
      >
        <div
          className="studio-chat-indeterminate-progress-fill absolute inset-y-0 left-0 w-[40%] rounded-full bg-indigo-500 dark:bg-indigo-400"
          aria-hidden
        />
      </div>
    </div>
  );
}

'use client';

import * as React from 'react';

/**
 * Three-dot bouncing typing indicator (#258). Used inside the assistant
 * bubble while the model is composing a response.
 */
export function ChatTypingIndicator({ label = 'Thinking…' }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="studio-ai-chat-typing"
      className="flex items-center gap-2 text-gray-600 dark:text-gray-300"
    >
      <span className="flex items-end gap-1" aria-hidden>
        <span className="h-1.5 w-1.5 rounded-full bg-gray-500 dark:bg-gray-400 animate-bounce [animation-delay:-0.2s]" />
        <span className="h-1.5 w-1.5 rounded-full bg-gray-500 dark:bg-gray-400 animate-bounce [animation-delay:-0.1s]" />
        <span className="h-1.5 w-1.5 rounded-full bg-gray-500 dark:bg-gray-400 animate-bounce" />
      </span>
      <span className="text-xs">{label}</span>
    </div>
  );
}

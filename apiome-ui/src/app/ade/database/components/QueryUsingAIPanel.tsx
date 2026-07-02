'use client';

import * as React from 'react';
import * as Dialog from '@radix-ui/react-dialog';

interface QueryUsingAIPanelProps {
  open: boolean;
  onClose: () => void;
  versionId: string;
  tableName: string;
  classSchemaId: string | null;
}

export default function QueryUsingAIPanel({
  open,
  onClose,
  versionId,
  tableName,
}: QueryUsingAIPanelProps) {
  const [query, setQuery] = React.useState('');
  const [response, setResponse] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [tableNames, setTableNames] = React.useState<string[]>([]);

  React.useEffect(() => {
    if (open && versionId) {
      fetch(`/api/database/versions/${versionId}/tables`)
        .then((r) => r.json())
        .then((data) => {
          if (data.success && data.tables) {
            setTableNames((data.tables as { class_name: string }[]).map((t) => t.class_name));
          }
        })
        .catch(() => setTableNames([]));
    }
  }, [open, versionId]);

  const handleSubmit = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setResponse('');
    try {
      const res = await fetch('/api/ollama/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'llama3.2',
          task: 'data_query',
          tableNames,
          currentTableName: tableName,
          messages: [{ role: 'user', content: query.trim() }],
        }),
      });
      if (!res.ok || !res.body) {
        setResponse('Request failed.');
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let text = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const payload = line.slice(6);
            if (payload === '[DONE]') continue;
            try {
              const parsed = JSON.parse(payload);
              if (parsed.content) text += parsed.content;
            } catch {
              // ignore
            }
          }
        }
      }
      setResponse(text || 'No response.');
    } catch (e) {
      setResponse(e instanceof Error ? e.message : 'Error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-lg max-h-[80vh] flex flex-col rounded-lg bg-white dark:bg-gray-800 shadow-lg border border-gray-200 dark:border-gray-700 overflow-hidden"
        >
          <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white p-4 pb-0">
            Query using AI
          </Dialog.Title>
          <Dialog.Description className="text-sm text-gray-500 dark:text-gray-400 px-4 pt-1">
            Ask a question about the data. The AI will suggest how to search or filter (e.g. which table or criteria).
          </Dialog.Description>
          <div className="p-4 flex flex-col gap-3 flex-1 min-h-0">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Find all records where status is active"
              className="w-full min-h-[80px] px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm resize-y"
              disabled={loading}
            />
            <button
              type="button"
              onClick={handleSubmit}
              disabled={loading || !query.trim()}
              className="self-end px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? 'Thinking...' : 'Submit'}
            </button>
            {response && (
              <div className="flex-1 min-h-0 overflow-auto rounded-lg border border-gray-200 dark:border-gray-600 p-3 bg-gray-50 dark:bg-gray-900 text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                {response}
              </div>
            )}
          </div>
          <div className="p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-600 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
            >
              Close
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

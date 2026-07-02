'use client';

import React, { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';

export interface ExtensionsEditorProps {
  value: Record<string, any>;
  onChange: (extensions: Record<string, any>) => void;
  disabled?: boolean;
  size?: 'small' | 'medium';
}

export const ExtensionsEditor: React.FC<ExtensionsEditorProps> = ({
  value = {},
  onChange,
  disabled = false,
  size = 'medium',
}) => {
  const [keyInput, setKeyInput] = useState('');
  const [valueInput, setValueInput] = useState('');
  const [error, setError] = useState('');

  const handleAdd = () => {
    if (!keyInput.trim()) {
      setError('Key cannot be empty');
      return;
    }
    const trimmedKey = keyInput.trim();
    if (!trimmedKey.startsWith('x-')) {
      setError('Extension keys must start with "x-"');
      return;
    }
    if (!/^x-[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
      setError('Extension keys can only contain letters, numbers, hyphens, and underscores after "x-"');
      return;
    }
    if (trimmedKey in value) {
      setError('This extension key already exists');
      return;
    }
    let parsedValue: any;
    const trimmedValue = valueInput.trim();
    if (!trimmedValue) {
      setError('Value cannot be empty');
      return;
    }
    try {
      parsedValue = JSON.parse(trimmedValue);
    } catch {
      parsedValue = trimmedValue;
    }
    onChange({ ...value, [trimmedKey]: parsedValue });
    setKeyInput('');
    setValueInput('');
    setError('');
  };

  const handleRemove = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleAdd();
    }
  };

  const extensionEntries = Object.entries(value).sort(([a], [b]) => a.localeCompare(b));
  const inputHeight = size === 'small' ? 'h-10' : 'h-14';

  return (
    <div>
      <p className="text-sm font-medium mb-1">Extensions</p>
      <p className="text-xs text-slate-500 dark:text-slate-400 block mb-4">
        Add custom x- prefixed properties per OpenAPI 3.1 specification. Values can be any valid JSON.
      </p>

      {error && (
        <div
          role="alert"
          className="mb-4 px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 text-sm flex items-center justify-between"
        >
          <span>{error}</span>
          <button type="button" onClick={() => setError('')} className="text-red-600 hover:text-red-800 dark:text-red-400">
            ×
          </button>
        </div>
      )}

      <div className="mb-4">
        <div className="grid grid-cols-[1fr_2fr_auto] gap-2 mb-2">
          <input
            aria-label="Key"
            className={`w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm ${inputHeight}`}
            placeholder="x-custom-property"
            value={keyInput}
            onChange={(e) => { setKeyInput(e.target.value); setError(''); }}
            onKeyDown={handleKeyPress}
            disabled={disabled}
          />
          <input
            aria-label="Value (JSON)"
            className={`w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 text-sm ${inputHeight}`}
            placeholder='true, 42, "text", or {"key": "value"}'
            value={valueInput}
            onChange={(e) => { setValueInput(e.target.value); setError(''); }}
            onKeyDown={handleKeyPress}
            disabled={disabled}
          />
          <button
            type="button"
            onClick={handleAdd}
            disabled={!keyInput.trim() || !valueInput.trim() || disabled}
            className={`rounded-lg flex items-center justify-center bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:pointer-events-none ${inputHeight} w-14`}
          >
            <Plus className="w-5 h-5" />
          </button>
        </div>
        <p className="text-xs text-slate-500">Key must start with x-</p>
      </div>

      {extensionEntries.length > 0 && (
        <ul className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 max-h-[300px] overflow-auto divide-y divide-slate-200 dark:divide-slate-700 list-none p-0 m-0">
          {extensionEntries.map(([key, val]) => (
            <li
              key={key}
              className="flex items-start gap-2 px-3 py-2 border-b border-slate-200 dark:border-slate-700 last:border-b-0"
            >
              <div className="flex-1 min-w-0 my-0.5">
                <span className="font-mono text-sm font-semibold text-indigo-600 dark:text-indigo-400">{key}</span>
                <p className="font-mono text-[13px] text-slate-500 dark:text-slate-400 mt-1 break-words">
                  {JSON.stringify(val)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => handleRemove(key)}
                disabled={disabled}
                className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-400"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {extensionEntries.length === 0 && (
        <div className="p-6 rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/30 text-center">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No extensions defined. Extensions allow you to add custom metadata that can be used by tools and documentation generators.
          </p>
        </div>
      )}
    </div>
  );
};

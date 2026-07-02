'use client';

import React, { useState } from 'react';
import { CheckCircle, XCircle, ChevronDown, ChevronUp } from 'lucide-react';

interface RegexTesterProps {
  pattern: string;
}

export const RegexTester: React.FC<RegexTesterProps> = ({ pattern }) => {
  const [testString, setTestString] = useState('');
  const [testResult, setTestResult] = useState<{ matches: boolean; error?: string } | null>(null);
  const [expanded, setExpanded] = useState(false);

  const handleTest = () => {
    if (!pattern.trim()) {
      setTestResult({ matches: false, error: 'Please enter a regex pattern first' });
      return;
    }
    try {
      const regex = new RegExp(pattern);
      const matches = regex.test(testString);
      setTestResult({ matches });
    } catch (error) {
      setTestResult({
        matches: false,
        error: `Invalid regex: ${error instanceof Error ? error.message : 'Unknown error'}`
      });
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleTest();
    }
  };

  if (!pattern.trim()) {
    return null;
  }

  return (
    <div className="mb-4 mt-2">
      <div className="flex items-center gap-2 mb-2">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800"
        >
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          Test Regex
        </button>
        {testResult && !testResult.error && (
          <span
            className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium ${
              testResult.matches ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400'
            }`}
          >
            {testResult.matches ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
            {testResult.matches ? 'Match' : 'No Match'}
          </span>
        )}
      </div>

      {expanded && (
        <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50">
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
            Current pattern: <code className="px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-800 dark:text-slate-200">{pattern}</code>
          </p>

          <div className="flex gap-2 items-start">
            <input
              type="text"
              aria-label="Test String"
              className="flex-1 px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm"
              placeholder="Enter text to test against the pattern"
              value={testString}
              onChange={(e) => setTestString(e.target.value)}
              onKeyDown={handleKeyDown}
            />
            <button
              type="button"
              onClick={handleTest}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-700 min-w-[80px] mt-0.5"
            >
              Test
            </button>
          </div>

          {testResult && (
            <div className="mt-4">
              {testResult.error ? (
                <div className="py-2 px-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 text-sm">
                  {testResult.error}
                </div>
              ) : (
                <div
                  className={`py-2 px-3 rounded-lg text-sm flex items-center gap-2 ${
                    testResult.matches
                      ? 'bg-green-50 dark:bg-green-900/20 text-green-800 dark:text-green-200'
                      : 'bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-200'
                  }`}
                >
                  {testResult.matches ? <CheckCircle className="w-4 h-4 flex-shrink-0" /> : <XCircle className="w-4 h-4 flex-shrink-0" />}
                  {testResult.matches ? 'Pattern matches the test string' : 'Pattern does not match the test string'}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

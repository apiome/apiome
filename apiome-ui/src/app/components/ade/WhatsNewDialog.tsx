'use client';

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { Markdown } from '@/app/components/ui/Markdown';
import { githubMarkdownComponents } from '@/app/components/ui/markdownGithubComponents';

interface WhatsNewDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

const WhatsNewDialog: React.FC<WhatsNewDialogProps> = ({ isOpen, onClose }) => {
  const [markdownContent, setMarkdownContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (isOpen) {
      fetch('/WHATS_NEW.md')
        .then((response) => response.text())
        .then((text) => {
          setMarkdownContent(text);
          setIsLoading(false);
        })
        .catch((error) => {
          console.error("Error loading What's New content:", error);
          setMarkdownContent("# Error\n\nFailed to load What's New content.");
          setIsLoading(false);
        });
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[3000] flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl max-h-[85vh] bg-white dark:bg-gray-800 rounded-xl shadow-2xl overflow-hidden border border-gray-200 dark:border-gray-700"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50/80 dark:bg-gray-800/80">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">What&apos;s New</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            aria-label="Close dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-5 overflow-y-auto max-h-[calc(85vh-80px)] scroll-smooth">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="text-gray-500 dark:text-gray-400 animate-pulse">Loading…</div>
            </div>
          ) : (
            <Markdown
              variant="article"
              allowHtml
              components={githubMarkdownComponents}
            >
              {markdownContent}
            </Markdown>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
};

export default WhatsNewDialog;

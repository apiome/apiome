'use client';

import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Copy, Link2, X } from 'lucide-react';

export type ClassDropAction = 'copy' | 'reference' | 'cancel';

interface ClassDropChoiceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  className?: string;
  onChoice: (action: ClassDropAction) => void;
  showArrayOption?: boolean;
  arrayOptionChecked?: boolean;
  onArrayOptionCheckedChange?: (checked: boolean) => void;
}

export default function ClassDropChoiceDialog({
  open,
  onOpenChange,
  className = 'class',
  onChoice,
  showArrayOption = false,
  arrayOptionChecked = false,
  onArrayOptionCheckedChange,
}: ClassDropChoiceDialogProps) {
  const handleChoice = (action: ClassDropAction) => {
    onChoice(action);
    onOpenChange(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[9999]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10000] w-full max-w-md rounded-xl shadow-2xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-0 focus:outline-none"
        >
          {/* Header */}
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white">
              Add Class to Response
            </Dialog.Title>
            <Dialog.Description className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              How would you like to use &quot;{className}&quot; in this response?
            </Dialog.Description>
          </div>

          {/* Options */}
          <div className="p-4 space-y-3">
            {/* Copy Properties Option */}
            <button
              onClick={() => handleChoice('copy')}
              className="w-full flex items-start gap-4 p-4 rounded-lg border-2 border-gray-200 dark:border-gray-600 hover:border-indigo-500 dark:hover:border-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-all text-left group"
            >
              <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-indigo-100 dark:bg-indigo-900/30 flex items-center justify-center group-hover:bg-indigo-200 dark:group-hover:bg-indigo-800/40 transition-colors">
                <Copy className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-gray-900 dark:text-white">
                  Copy properties into response schema
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Copies the class properties into this response. The schema is static and you can edit it here at any time. Changes to the original class won&apos;t affect this response.
                </p>
              </div>
            </button>

            {/* Use as $ref Option */}
            <button
              onClick={() => handleChoice('reference')}
              className="w-full flex items-start gap-4 p-4 rounded-lg border-2 border-gray-200 dark:border-gray-600 hover:border-blue-500 dark:hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-all text-left group"
            >
              <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center group-hover:bg-blue-200 dark:group-hover:bg-blue-800/40 transition-colors">
                <Link2 className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-medium text-gray-900 dark:text-white">
                  Use as $ref (reference)
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  References the class with $ref. The node will show &quot;$ref&quot; and display the class properties as read-only. If the class definition changes, this response updates automatically; you cannot edit the schema here.
                </p>
              </div>
            </button>

            {showArrayOption && (
              <label className="flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-600 px-3 py-2 text-sm text-gray-700 dark:text-gray-200">
                <input
                  type="checkbox"
                  checked={arrayOptionChecked}
                  onChange={(e) => onArrayOptionCheckedChange?.(e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span>Link as array response (schema type: array)</span>
              </label>
            )}
          </div>

          {/* Footer */}
          <div className="p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end">
            <button
              onClick={() => handleChoice('cancel')}
              className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>

          {/* Close button */}
          <Dialog.Close asChild>
            <button
              className="absolute top-4 right-4 p-1 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

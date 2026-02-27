'use client';

import * as React from 'react';
import * as Dialog from '@radix-ui/react-dialog';

interface InsertStubModalProps {
  open: boolean;
  onClose: () => void;
  tableName: string;
}

export default function InsertStubModal({ open, onClose, tableName }: InsertStubModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md rounded-lg bg-white dark:bg-gray-800 p-6 shadow-lg border border-gray-200 dark:border-gray-700 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0">
          <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-white">
            Insert record
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            Insertion into &quot;{tableName}&quot; is not yet implemented. When available, new records will be
            validated against the class schema (JSON Schema) for this version before being written to the data store.
          </Dialog.Description>
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700"
            >
              Close
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

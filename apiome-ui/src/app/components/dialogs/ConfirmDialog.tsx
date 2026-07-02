'use client';

import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { AlertTriangle, Info, CheckCircle, XCircle } from 'lucide-react';

export type ConfirmDialogVariant = 'danger' | 'warning' | 'info' | 'success';

interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  message: string | React.ReactNode;
  variant?: ConfirmDialogVariant;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  title,
  message,
  variant = 'warning',
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
}) => {
  const getIcon = () => {
    switch (variant) {
      case 'danger':
        return <XCircle className="h-6 w-6 text-red-600" />;
      case 'warning':
        return <AlertTriangle className="h-6 w-6 text-yellow-600" />;
      case 'info':
        return <Info className="h-6 w-6 text-blue-600" />;
      case 'success':
        return <CheckCircle className="h-6 w-6 text-green-600" />;
    }
  };

  const getConfirmButtonClass = () => {
    const base = 'px-4 py-2 rounded-lg font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2';
    switch (variant) {
      case 'danger':
        return `${base} bg-red-600 text-white hover:bg-red-700 focus:ring-red-500`;
      case 'warning':
        return `${base} bg-amber-600 text-white hover:bg-amber-700 focus:ring-amber-500`;
      case 'info':
        return `${base} bg-blue-600 text-white hover:bg-blue-700 focus:ring-blue-500`;
      case 'success':
        return `${base} bg-green-600 text-white hover:bg-green-700 focus:ring-green-500`;
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(open) => !open && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[10001]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10002] w-full max-w-sm bg-white dark:bg-gray-900 rounded-xl shadow-xl p-0 flex flex-col max-h-[90vh]"
          onEscapeKeyDown={onCancel}
          onPointerDownOutside={onCancel}
        >
          <div className="p-6 pb-2">
            <Dialog.Title className="flex items-center gap-3 text-xl font-semibold text-gray-900 dark:text-gray-100">
              {getIcon()}
              <span>{title || 'Confirm Action'}</span>
            </Dialog.Title>
          </div>
          <div className="px-6 py-2 flex-1 overflow-auto">
            {typeof message === 'string' ? (
              <p className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                {message}
              </p>
            ) : (
              <div className="text-gray-700 dark:text-gray-300">{message}</div>
            )}
          </div>
          <div className="flex justify-end gap-2 p-4 pt-4">
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-400"
            >
              {cancelLabel}
            </button>
            <button
              type="button"
              onClick={onConfirm}
              className={getConfirmButtonClass()}
              autoFocus
            >
              {confirmLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};

export default ConfirmDialog;

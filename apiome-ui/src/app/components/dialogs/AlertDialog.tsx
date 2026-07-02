'use client';

import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { AlertTriangle, Info, CheckCircle, XCircle } from 'lucide-react';

export type AlertDialogVariant = 'error' | 'warning' | 'info' | 'success';

interface AlertDialogProps {
  open: boolean;
  title?: string;
  message: string | React.ReactNode;
  variant?: AlertDialogVariant;
  confirmLabel?: string;
  onClose: () => void;
}

const AlertDialog: React.FC<AlertDialogProps> = ({
  open,
  title,
  message,
  variant = 'info',
  confirmLabel = 'OK',
  onClose,
}) => {
  const getIcon = () => {
    switch (variant) {
      case 'error':
        return <XCircle className="h-6 w-6 text-red-600" />;
      case 'warning':
        return <AlertTriangle className="h-6 w-6 text-yellow-600" />;
      case 'info':
        return <Info className="h-6 w-6 text-blue-600" />;
      case 'success':
        return <CheckCircle className="h-6 w-6 text-green-600" />;
    }
  };

  const getTitle = () => {
    if (title) return title;
    switch (variant) {
      case 'error':
        return 'Error';
      case 'warning':
        return 'Warning';
      case 'info':
        return 'Information';
      case 'success':
        return 'Success';
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[10001]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10002] w-full max-w-sm bg-white dark:bg-gray-900 rounded-xl shadow-xl p-0 flex flex-col max-h-[90vh]"
          onEscapeKeyDown={onClose}
          onPointerDownOutside={onClose}
        >
          <div className="p-6 pb-2">
            <Dialog.Title className="flex items-center gap-3 text-xl font-semibold text-gray-900 dark:text-gray-100">
              {getIcon()}
              <span>{getTitle()}</span>
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
          <div className="flex justify-end p-4 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
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

export default AlertDialog;

'use client';

import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import ConfirmDialog, { ConfirmDialogVariant } from '../dialogs/ConfirmDialog';
import AlertDialog, { AlertDialogVariant } from '../dialogs/AlertDialog';

interface ConfirmOptions {
  title?: string;
  message: string | ReactNode;
  variant?: ConfirmDialogVariant;
  confirmLabel?: string;
  cancelLabel?: string;
}

interface AlertOptions {
  title?: string;
  message: string | ReactNode;
  variant?: AlertDialogVariant;
  confirmLabel?: string;
}

interface DialogContextType {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  alert: (options: AlertOptions) => Promise<void>;
}

const DialogContext = createContext<DialogContextType | undefined>(undefined);

interface DialogProviderProps {
  children: ReactNode;
}

export const DialogProvider: React.FC<DialogProviderProps> = ({ children }) => {
  const [confirmDialog, setConfirmDialog] = useState<{
    open: boolean;
    options: ConfirmOptions;
    resolve: (value: boolean) => void;
  } | null>(null);

  const [alertDialog, setAlertDialog] = useState<{
    open: boolean;
    options: AlertOptions;
    resolve: () => void;
  } | null>(null);

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setConfirmDialog({
        open: true,
        options,
        resolve,
      });
    });
  }, []);

  const alert = useCallback((options: AlertOptions): Promise<void> => {
    return new Promise((resolve) => {
      setAlertDialog({
        open: true,
        options,
        resolve,
      });
    });
  }, []);

  const handleConfirm = () => {
    if (confirmDialog) {
      confirmDialog.resolve(true);
      setConfirmDialog(null);
    }
  };

  const handleCancel = () => {
    if (confirmDialog) {
      confirmDialog.resolve(false);
      setConfirmDialog(null);
    }
  };

  const handleAlertClose = () => {
    if (alertDialog) {
      alertDialog.resolve();
      setAlertDialog(null);
    }
  };

  return (
    <DialogContext.Provider value={{ confirm, alert }}>
      {children}
      {confirmDialog && (
        <ConfirmDialog
          open={confirmDialog.open}
          title={confirmDialog.options.title}
          message={confirmDialog.options.message as string | React.ReactNode}
          variant={confirmDialog.options.variant}
          confirmLabel={confirmDialog.options.confirmLabel}
          cancelLabel={confirmDialog.options.cancelLabel}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      )}
      {alertDialog && (
        <AlertDialog
          open={alertDialog.open}
          title={alertDialog.options.title}
          message={alertDialog.options.message as string | React.ReactNode}
          variant={alertDialog.options.variant}
          confirmLabel={alertDialog.options.confirmLabel}
          onClose={handleAlertClose}
        />
      )}
    </DialogContext.Provider>
  );
};

export const useDialog = (): DialogContextType => {
  const context = useContext(DialogContext);
  if (!context) {
    throw new Error('useDialog must be used within a DialogProvider');
  }
  return context;
};


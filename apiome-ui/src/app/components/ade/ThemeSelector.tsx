'use client';

import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X, Check, Monitor } from 'lucide-react';
import { useTheme } from '../../providers/ThemeProvider';

interface ThemeSelectorProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ThemeSelector({ isOpen, onClose }: ThemeSelectorProps) {
  const { currentTheme, setTheme, availableThemes, isSystemTheme } = useTheme();

  const handleThemeSelect = (themeId: string) => {
    setTheme(themeId);
    onClose();
  };

  // Get current system preference for display
  const getSystemPreference = () => {
    if (typeof window !== 'undefined') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'Dark' : 'Light';
    }
    return 'Light';
  };

  return (
    <Dialog.Root open={isOpen} onOpenChange={onClose}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[9998]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 w-full max-w-2xl max-h-[80vh] overflow-hidden z-[9999]"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
            <div>
              <Dialog.Title className="text-xl font-semibold text-gray-900 dark:text-gray-100">
                Select Theme
              </Dialog.Title>
              <Dialog.Description className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Choose your preferred color theme for the application
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                aria-label="Close"
              >
                <X className="w-5 h-5 text-gray-500 dark:text-gray-400" />
              </button>
            </Dialog.Close>
          </div>

          {/* Theme Grid */}
          <div className="p-6 overflow-y-auto max-h-[calc(80vh-80px)]">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {availableThemes.map((theme) => (
                <button
                  key={theme.id}
                  onClick={() => handleThemeSelect(theme.id)}
                  className={`
                    relative p-4 rounded-xl border-2 transition-all text-left
                    hover:shadow-lg hover:scale-[1.02]
                    ${
                      currentTheme.id === theme.id
                        ? 'border-indigo-500 ring-2 ring-indigo-500/20'
                        : 'border-gray-200 dark:border-gray-700 hover:border-indigo-300 dark:hover:border-indigo-600'
                    }
                  `}
                >
                  {/* Selected indicator */}
                  {currentTheme.id === theme.id && (
                    <div className="absolute top-2 right-2 w-6 h-6 bg-indigo-500 rounded-full flex items-center justify-center">
                      <Check className="w-4 h-4 text-white" />
                    </div>
                  )}

                  {/* Theme name and description */}
                  <div className="mb-3">
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
                      {theme.id === 'system' && <Monitor className="w-5 h-5" />}
                      {theme.name}
                      {theme.id === 'system' && isSystemTheme && (
                        <span className="text-xs font-normal px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300">
                          Currently: {getSystemPreference()}
                        </span>
                      )}
                    </h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                      {theme.description}
                    </p>
                  </div>

                  {/* Color palette preview - show special gradient for system theme */}
                  {theme.id === 'system' ? (
                    <div className="flex gap-2">
                      <div className="w-12 h-12 rounded-lg shadow-sm border border-gray-200 dark:border-gray-600 bg-gradient-to-br from-white to-gray-100" title="Light mode" />
                      <div className="w-12 h-12 rounded-lg shadow-sm border border-gray-200 dark:border-gray-600 bg-gradient-to-br from-gray-700 to-gray-900" title="Dark mode" />
                      <div className="w-12 h-12 rounded-lg shadow-sm border border-gray-200 dark:border-gray-600 flex items-center justify-center bg-gray-50 dark:bg-gray-700">
                        <Monitor className="w-6 h-6 text-gray-400" />
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <div
                        className="w-12 h-12 rounded-lg shadow-sm border border-gray-200 dark:border-gray-600"
                        style={{ backgroundColor: theme.colors.background }}
                        title="Background"
                      />
                      <div
                        className="w-12 h-12 rounded-lg shadow-sm border border-gray-200 dark:border-gray-600"
                        style={{ backgroundColor: theme.colors.primary }}
                        title="Primary"
                      />
                      <div
                        className="w-12 h-12 rounded-lg shadow-sm border border-gray-200 dark:border-gray-600"
                        style={{ backgroundColor: theme.colors.secondary }}
                        title="Secondary"
                      />
                      <div
                        className="w-12 h-12 rounded-lg shadow-sm border border-gray-200 dark:border-gray-600"
                        style={{ backgroundColor: theme.colors.accent }}
                        title="Accent"
                      />
                    </div>
                  )}

                  {/* Preview card - show special preview for system theme */}
                  {theme.id === 'system' ? (
                    <div className="mt-3 p-3 rounded-lg border border-gray-200 dark:border-gray-600 bg-gradient-to-r from-white to-gray-800">
                      <div className="text-xs font-medium mb-1 text-gray-700">Auto-switches</div>
                      <div className="text-xs text-gray-500">Based on your OS setting</div>
                    </div>
                  ) : (
                    <div
                      className="mt-3 p-3 rounded-lg border"
                      style={{
                        backgroundColor: theme.colors.card,
                        borderColor: theme.colors.border,
                        color: theme.colors.cardForeground,
                      }}
                    >
                      <div className="text-xs font-medium mb-1">Preview</div>
                      <div className="text-xs opacity-75">This is how text will look</div>
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
            <Dialog.Close asChild>
              <button
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
              >
                Close
              </button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}


'use client';

export type ImportSourceTabId =
  | 'file'
  | 'url'
  | 'clipboard'
  | 'git'
  | 'swaggerhub'
  | 'registry';

const TABS: { id: ImportSourceTabId; label: string; disabled?: boolean }[] = [
  { id: 'file', label: 'File' },
  { id: 'url', label: 'URL' },
  { id: 'clipboard', label: 'Clipboard' },
  { id: 'git', label: 'Git' },
  { id: 'swaggerhub', label: 'SwaggerHub' },
  { id: 'registry', label: 'Registry', disabled: true },
];

const TAB_ICONS: Record<ImportSourceTabId, string> = {
  file: '📁',
  url: '🔗',
  clipboard: '📋',
  git: '🐙',
  swaggerhub: '☁️',
  registry: '📦',
};

export interface ImportSourceTabBarProps {
  active: ImportSourceTabId;
  onSelect: (id: ImportSourceTabId) => void;
  className?: string;
  /** Additional tab ids to disable (e.g. SwaggerHub when this flow does not support it). */
  disabledIds?: ImportSourceTabId[];
}

export function ImportSourceTabBar({ active, onSelect, className = '', disabledIds }: ImportSourceTabBarProps) {
  return (
    <div
      role="tablist"
      aria-label="Import source"
      className={`flex flex-wrap gap-1 border-b border-gray-200 dark:border-gray-700 ${className}`}
    >
      {TABS.map(({ id, label, disabled }) => {
        const isDisabled = Boolean(disabled) || Boolean(disabledIds?.includes(id));
        const isActive = active === id;
        const icon = TAB_ICONS[id];
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-disabled={isDisabled || undefined}
            disabled={isDisabled}
            onClick={() => !isDisabled && onSelect(id)}
            title={isDisabled ? 'Coming soon' : undefined}
            className={`px-3 py-2 text-sm font-medium transition-colors rounded-t-md border-b-2 -mb-px ${
              isDisabled
                ? 'text-gray-400 dark:text-gray-600 cursor-not-allowed opacity-50 border-transparent'
                : isActive
                  ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                  : 'border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 hover:border-gray-300 dark:hover:border-gray-600'
            }`}
          >
            <span aria-hidden="true">{icon}</span>{' '}{label}
          </button>
        );
      })}
    </div>
  );
}

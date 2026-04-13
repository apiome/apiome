'use client';

import React, { useMemo, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Check, ChevronsUpDown, Search } from 'lucide-react';
import { cn } from '../../../../../../lib/utils';
import { Input } from '../../../../components/ui/Input';
import { useDarkMode } from '../../../../hooks/useDarkMode';

export interface ReuseSearchItem {
  id: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

interface ReuseSearchComboboxProps {
  items: ReuseSearchItem[];
  value: string;
  onValueChange: (id: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
  triggerClassName?: string;
  'aria-label'?: string;
}

/** Searchable combobox (Command-style) for reuse libraries: classes, shared parameters, responses. */
export default function ReuseSearchCombobox({
  items,
  value,
  onValueChange,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  emptyText = 'No matches.',
  disabled = false,
  className,
  triggerClassName,
  'aria-label': ariaLabel,
}: ReuseSearchComboboxProps) {
  const isDark = useDarkMode();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => {
      const hay = `${it.label} ${it.description ?? ''}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, query]);

  const selected = items.find((i) => i.id === value);

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQuery('');
      }}
    >
      <div className={cn('w-full', className)}>
        <Popover.Trigger asChild>
          <button
            type="button"
            disabled={disabled}
            aria-expanded={open}
            aria-label={ariaLabel ?? placeholder}
            className={cn(
              'flex h-9 w-full items-center justify-between gap-2 rounded-md border px-3 text-left text-xs font-normal outline-none transition-colors',
              'focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-slate-900',
              isDark
                ? 'border-slate-600 bg-slate-800 text-slate-100'
                : 'border-slate-200 bg-white text-slate-900',
              disabled && 'cursor-not-allowed opacity-50',
              triggerClassName
            )}
          >
            <span className="min-w-0 flex-1 truncate">{selected?.label ?? placeholder}</span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" aria-hidden />
          </button>
        </Popover.Trigger>
      </div>
      <Popover.Portal>
        <Popover.Content
          className={cn(
            'z-[10050] w-[var(--radix-popover-trigger-width)] min-w-[240px] rounded-md border p-0 shadow-lg',
            isDark ? 'border-slate-600 bg-slate-900' : 'border-slate-200 bg-white'
          )}
          sideOffset={4}
          align="start"
          onOpenAutoFocus={(e) => e.preventDefault()}
        >
          <div
            className={cn('border-b p-2', isDark ? 'border-slate-700' : 'border-slate-200')}
          >
            <div className="relative">
              <Search
                className={cn(
                  'pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2',
                  isDark ? 'text-slate-500' : 'text-slate-400'
                )}
                aria-hidden
              />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className={cn(
                  'h-8 pl-8 text-xs',
                  isDark ? 'border-slate-600 bg-slate-800' : ''
                )}
                placeholder={searchPlaceholder}
                autoComplete="off"
              />
            </div>
          </div>
          <div className="max-h-60 overflow-y-auto p-1">
            {filtered.length === 0 ? (
              <div
                className={cn(
                  'py-6 text-center text-xs',
                  isDark ? 'text-slate-500' : 'text-slate-500'
                )}
              >
                {emptyText}
              </div>
            ) : (
              <ul className="space-y-0.5" role="listbox">
                {filtered.map((item) => {
                  const isSelected = value === item.id;
                  return (
                    <li key={item.id} role="option" aria-selected={isSelected}>
                      <button
                        type="button"
                        disabled={item.disabled}
                        onClick={() => {
                          if (item.disabled) return;
                          onValueChange(item.id);
                          setOpen(false);
                          setQuery('');
                        }}
                        className={cn(
                          'flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors',
                          item.disabled
                            ? 'cursor-not-allowed opacity-50'
                            : isDark
                              ? 'hover:bg-slate-800'
                              : 'hover:bg-slate-100',
                          isSelected && (isDark ? 'bg-slate-800' : 'bg-indigo-50')
                        )}
                      >
                        <Check
                          className={cn(
                            'mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-600',
                            isSelected ? 'opacity-100' : 'opacity-0'
                          )}
                          aria-hidden
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium text-slate-900 dark:text-slate-100">
                            {item.label}
                          </span>
                          {item.description ? (
                            <span className="mt-0.5 block text-[10px] text-slate-500 dark:text-slate-400">
                              {item.description}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

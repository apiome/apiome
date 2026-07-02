'use client';

import * as React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Command } from 'cmdk';
import { usePathname } from 'next/navigation';
import { GitBranch, HelpCircle } from 'lucide-react';
import { toast } from 'sonner';
import { useStudio } from '../StudioContext';
import {
  matchesStudioGitPaletteShortcut,
  STUDIO_GIT_PALETTE_ACTION_ORDER,
  STUDIO_GIT_PALETTE_LABELS,
  STUDIO_KEYBINDING_CHEATSHEET_LINES,
  type StudioGitPaletteActionId,
} from '@/app/utils/studio-keybindings';

function paletteUnavailableToast() {
  toast.message('Open the Designer canvas (editor) with a project and revision selected to run git actions from here.');
}

export function GitCommandPalette() {
  const pathname = usePathname();
  const { invokeGitPaletteAction } = useStudio();
  const [open, setOpen] = React.useState(false);
  const [cheatsheetVisible, setCheatsheetVisible] = React.useState(false);
  const lastFocusRef = React.useRef<HTMLElement | null>(null);

  const inStudio = Boolean(pathname?.startsWith('/ade/studio'));

  React.useEffect(() => {
    if (!inStudio) return;

    const onKeyDown = (ev: KeyboardEvent) => {
      if (!matchesStudioGitPaletteShortcut(ev)) return;
      ev.preventDefault();
      lastFocusRef.current = document.activeElement as HTMLElement | null;
      setOpen(true);
    };

    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [inStudio]);

  const runAction = React.useCallback(
    (id: StudioGitPaletteActionId) => {
      const ok = invokeGitPaletteAction(id);
      if (!ok) {
        paletteUnavailableToast();
      }
      setOpen(false);
      setCheatsheetVisible(false);
    },
    [invokeGitPaletteAction]
  );

  const onOpenChange = React.useCallback((next: boolean) => {
    setOpen(next);
    if (!next) {
      setCheatsheetVisible(false);
      queueMicrotask(() => {
        lastFocusRef.current?.focus?.();
        lastFocusRef.current = null;
      });
    }
  }, []);

  if (!inStudio) {
    return null;
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[10060] bg-black/50" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-[min(20vh,8rem)] z-[10061] w-[min(100vw-2rem,28rem)] -translate-x-1/2 rounded-xl border border-gray-200 bg-white shadow-2xl outline-none dark:border-gray-600 dark:bg-gray-900"
          onCloseAutoFocus={(e) => {
            e.preventDefault();
          }}
        >
          <Dialog.Title className="sr-only">Git commands</Dialog.Title>
          <Command className="flex max-h-[min(70vh,32rem)] flex-col overflow-hidden rounded-xl" label="Git commands">
            <div className="flex items-center gap-2 border-b border-gray-100 px-3 dark:border-gray-700">
              <GitBranch className="h-4 w-4 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
              <Command.Input
                placeholder="Search git actions… (type ? for shortcuts)"
                className="flex h-11 w-full border-0 bg-transparent py-3 text-sm text-gray-900 outline-none placeholder:text-gray-400 dark:text-gray-100 dark:placeholder:text-gray-500"
                onValueChange={(v) => {
                  if (v.trim() === '?') {
                    setCheatsheetVisible(true);
                  }
                }}
              />
            </div>

            {cheatsheetVisible ? (
              <div className="max-h-40 overflow-y-auto border-b border-gray-100 px-3 py-2 text-xs dark:border-gray-700">
                <div className="mb-1 font-semibold text-gray-700 dark:text-gray-200">Keyboard shortcuts</div>
                <ul className="space-y-1.5 text-gray-600 dark:text-gray-300">
                  {STUDIO_KEYBINDING_CHEATSHEET_LINES.map((row) => (
                    <li key={row.description} className="flex justify-between gap-3">
                      <span className="font-mono text-[11px] text-indigo-700 dark:text-indigo-300">{row.keys}</span>
                      <span className="text-right">{row.description}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <Command.List className="max-h-[min(50vh,22rem)] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
                No matching commands.
              </Command.Empty>

              <Command.Group heading="Git" className="px-1 pb-2 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-gray-500 dark:[&_[cmdk-group-heading]]:text-gray-400">
                {STUDIO_GIT_PALETTE_ACTION_ORDER.map((id) => {
                  const meta = STUDIO_GIT_PALETTE_LABELS[id];
                  const searchBlob = `${id} ${meta.title} ${meta.hint}`;
                  return (
                    <Command.Item
                      key={id}
                      value={searchBlob}
                      onSelect={() => runAction(id)}
                      className="flex cursor-pointer flex-col gap-0.5 rounded-lg px-3 py-2 text-sm text-gray-900 aria-selected:bg-indigo-50 dark:text-gray-100 dark:aria-selected:bg-indigo-950/50"
                    >
                      <span className="font-medium">{meta.title}</span>
                      <span className="text-xs text-gray-500 dark:text-gray-400">{meta.hint}</span>
                    </Command.Item>
                  );
                })}
              </Command.Group>

              <Command.Group heading="Help" className="px-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-gray-500 dark:[&_[cmdk-group-heading]]:text-gray-400">
                <Command.Item
                  value="help cheatsheet shortcuts question keyboard"
                  onSelect={() => setCheatsheetVisible((v) => !v)}
                  className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-900 aria-selected:bg-indigo-50 dark:text-gray-100 dark:aria-selected:bg-indigo-950/50"
                >
                  <HelpCircle className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
                  <span className="font-medium">Keyboard shortcuts (?)</span>
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

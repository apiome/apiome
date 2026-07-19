'use client';

/**
 * Command palette for the Authoring shell (UXE-1.2).
 *
 * `Cmd/Ctrl+K` opens a searchable menu of destinations and scope switches.
 * Built on Radix Dialog for focus trapping, Escape handling and focus restore,
 * and on cmdk for the listbox roles and arrow-key semantics; filtering is done
 * by `filterAuthoringCommands` so ranking is testable without a DOM.
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';
import * as Dialog from '@radix-ui/react-dialog';
import { Command } from 'cmdk';
import {
  buildAuthoringCommands,
  filterAuthoringCommands,
  groupAuthoringCommands,
  type AuthoringCommand,
} from '@lib/authoring/commands';
import { AUTHORING_SHORTCUT_HINTS } from '@lib/authoring/keybindings';
import { isSlashSearchEnabled, setSlashSearchEnabled } from '@lib/authoring/shortcut-preferences';
import { cn } from '@lib/utils';
import {
  authoringKbdClass,
  authoringPaletteContentClass,
  authoringPaletteInputClass,
  authoringPaletteItemClass,
  authoringPaletteOverlayClass,
} from '../authoringClasses';
import { useAuthoring } from '../AuthoringContext';
import AuthoringIcon from './AuthoringIcon';

/** Props for {@link AuthoringCommandPalette}. */
export type AuthoringCommandPaletteProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * Render the command palette.
 *
 * @param props - Controlled open state.
 */
export default function AuthoringCommandPalette({
  open,
  onOpenChange,
}: AuthoringCommandPaletteProps) {
  const router = useRouter();
  const {
    scope,
    projects,
    versions,
    entitledFlags,
    surface,
    setProjectId,
    setVersionId,
    setEnvironmentId,
  } = useAuthoring();
  const [query, setQuery] = React.useState('');
  const [slashEnabled, setSlashEnabled] = React.useState(true);

  // Start each visit from a clean query rather than the previous search, and
  // re-read the shortcut preference in case another view changed it.
  React.useEffect(() => {
    if (!open) {
      setQuery('');
      return;
    }
    setSlashEnabled(isSlashSearchEnabled());
  }, [open]);

  const commands = React.useMemo(
    () =>
      buildAuthoringCommands({
        scope,
        projects,
        versions,
        entitledFlags,
        activeSurfaceId: surface?.id,
      }),
    [scope, projects, versions, entitledFlags, surface]
  );

  const groups = React.useMemo(
    () => groupAuthoringCommands(filterAuthoringCommands(commands, query)),
    [commands, query]
  );

  const runCommand = React.useCallback(
    (command: AuthoringCommand) => {
      // Unavailable entries exist to explain access, not to act.
      if (command.unavailableReason) return;
      onOpenChange(false);

      switch (command.action.kind) {
        case 'navigate':
          router.push(command.action.href);
          break;
        case 'select-project':
          setProjectId(command.action.projectId);
          break;
        case 'select-version':
          setVersionId(command.action.versionId);
          break;
        case 'select-environment':
          setEnvironmentId(command.action.environmentId);
          break;
      }
    },
    [onOpenChange, router, setProjectId, setVersionId, setEnvironmentId]
  );

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={authoringPaletteOverlayClass} />
        <Dialog.Content className={authoringPaletteContentClass} aria-describedby={undefined}>
          <Dialog.Title className="sr-only">Authoring command palette</Dialog.Title>
          <Command shouldFilter={false} label="Authoring commands">
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Search destinations, projects, versions and environments…"
              className={authoringPaletteInputClass}
            />
            <Command.List className="max-h-80 overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
                No matches for “{query}”.
              </Command.Empty>

              {groups.map(({ group, commands: groupCommands }) => (
                <Command.Group
                  key={group}
                  heading={group}
                  className="px-1 py-1 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
                >
                  {groupCommands.map((command) => {
                    return (
                      <Command.Item
                        key={command.id}
                        value={command.id}
                        onSelect={() => runCommand(command)}
                        disabled={Boolean(command.unavailableReason)}
                        className={cn(
                          authoringPaletteItemClass,
                          command.unavailableReason && 'cursor-not-allowed opacity-60'
                        )}
                      >
                        <AuthoringIcon name={command.icon} className="mt-0.5 h-4 w-4 shrink-0" />
                        <span className="flex min-w-0 flex-col">
                          <span className="truncate font-medium normal-case tracking-normal text-gray-900 dark:text-gray-100">
                            {command.label}
                          </span>
                          <span className="truncate text-xs normal-case tracking-normal text-gray-500 dark:text-gray-400">
                            {command.unavailableReason ?? command.description}
                          </span>
                        </span>
                        {command.active ? (
                          <span className="ml-auto shrink-0 text-xs normal-case tracking-normal text-indigo-600 dark:text-indigo-400">
                            Current
                          </span>
                        ) : null}
                      </Command.Item>
                    );
                  })}
                </Command.Group>
              ))}
            </Command.List>
          </Command>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-gray-200 px-4 py-2 text-xs text-gray-500 dark:border-gray-700 dark:text-gray-400">
            {AUTHORING_SHORTCUT_HINTS.map((hint) => (
              <span key={hint.keys} className="inline-flex items-center gap-1.5">
                <kbd className={authoringKbdClass}>{hint.keys}</kbd>
                {hint.action}
              </span>
            ))}
            {/*
              WCAG 2.2 SC 2.1.4 requires a way to switch off a single-character
              shortcut. `/` is the only one the shell installs.
            */}
            <button
              type="button"
              onClick={() => setSlashEnabled(setSlashSearchEnabled(!slashEnabled))}
              aria-pressed={slashEnabled}
              className="ml-auto rounded border border-gray-300 px-2 py-0.5 hover:text-gray-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 dark:border-gray-600 dark:hover:text-gray-200"
            >
              Slash search: {slashEnabled ? 'on' : 'off'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

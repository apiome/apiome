'use client';

/**
 * The managed versions table of a pacticipant's **Versions** tab — PFX-8.11 (#7308).
 *
 * Authority: `docs/mockups/contracts/pacticipant.html` (Versions). One row per version: a select
 * box, the number, its branches, its tags with an inline **+ tag**, where it runs now, when it was
 * recorded, and its actions — a menu (**Pacts of this version**, **Can I deploy this?**, **Delete
 * version**) on a live row, **Restore** on a deleted one. A role without `pacts:create` sees no
 * **+ tag**; one without `pacts:delete` sees no delete, restore or select boxes for them.
 */

import * as React from 'react';
import Link from 'next/link';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Ellipsis, FileText, GitBranch, Rocket, Trash2, Undo2 } from 'lucide-react';
import { Button, Checkbox, Input } from '@/app/components/ui';
import { formatWhen, shortVersion, type PacticipantVersion } from '@lib/pact-pacticipants';
import {
  deleteBlock,
  deletedBy,
  restoreBlock,
  tagProblem,
  versionCanIDeployHref,
  versionMatrixHref,
  type DeletedVersion,
  type RunningIn,
} from '@lib/pact-pacticipant-versions';

/** The menu item class the shared `tnt-menu` styles. */
const MENU_ITEM_CLASS = 'tnt-menu__item';

/** Props for {@link VersionsManageTable}. */
export interface VersionsManageTableProps {
  /** The pacticipant's handle (for the row menu's links). */
  slug: string;
  /** The rows. */
  versions: (PacticipantVersion | DeletedVersion)[];
  /** Whether the rows are deleted versions (the Deleted view). */
  deleted: boolean;
  /** Where each version runs now, by number; `null` while it is not known. */
  runningIn: Map<string, RunningIn[]> | null;
  /** The selected version numbers. */
  selected: ReadonlySet<string>;
  /** Select or unselect one version, or every row (`null`). */
  onSelect: (number: string | null, on: boolean) => void;
  /** The caller may tag (`pacts:create`). */
  canTag: boolean;
  /** The caller may delete and restore (`pacts:delete`). */
  canDelete: boolean;
  /** Tag a version; answers the error to show under the input, or `null`. */
  onTag: (number: string, tag: string) => Promise<string | null>;
  /** Ask to delete one version (opens the confirmation). */
  onDelete: (number: string) => void;
  /** Restore one deleted version. */
  onRestore: (number: string) => void;
  /** The version a write is running for, which disables its row's actions. */
  busy: string | null;
}

/**
 * The inline **+ tag**: a link-styled button that becomes a small form.
 *
 * @param props - The version number, the tag write, and whether the row is busy.
 * @returns The control.
 */
function AddTag({
  number,
  onTag,
  disabled,
}: {
  number: string;
  onTag: (number: string, tag: string) => Promise<string | null>;
  disabled: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const [value, setValue] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  const [sending, setSending] = React.useState(false);
  const id = `ppx-tag-${number}`;
  if (!open) {
    return (
      <Button
        variant="link"
        size="sm"
        disabled={disabled}
        onClick={() => setOpen(true)}
        aria-label={`Add a tag to ${number}`}
        data-testid={`ppx-add-tag-${number}`}
      >
        + tag
      </Button>
    );
  }
  const submit = async () => {
    const tag = value.trim();
    const problem = tagProblem(tag);
    if (problem) {
      setError(problem);
      return;
    }
    setSending(true);
    const refused = await onTag(number, tag);
    setSending(false);
    if (refused) {
      setError(refused);
      return;
    }
    setValue('');
    setError(null);
    setOpen(false);
  };
  return (
    <form
      className="ppx-versions__tag-form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label htmlFor={id} className="sr-only">
        New tag for {number}
      </label>
      <Input
        id={id}
        className="ppx-versions__tag-input"
        value={value}
        autoFocus
        placeholder="prod"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => {
          setValue(event.target.value);
          setError(null);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false);
        }}
        data-testid={`ppx-tag-input-${number}`}
      />
      <Button type="submit" size="sm" variant="outline" disabled={sending}>
        {sending ? 'Adding…' : 'Add'}
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      {error ? (
        <p id={`${id}-error`} className="ppx__error ppx-versions__tag-error" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

/**
 * Where a version runs, as tags.
 *
 * @param props - The environments.
 * @returns The cell's content.
 */
function RunningCell({ running }: { running: RunningIn[] | undefined }) {
  if (!running || running.length === 0) return <span className="ppx__muted">—</span>;
  return (
    <span className="ppx__chips">
      {running.map((entry) => (
        <span
          key={entry.environment}
          className={entry.production ? 'ppx-versions__env ppx-versions__env--production' : 'ppx-versions__env'}
          title={entry.kind === 'released' ? 'Released and supported' : 'Deployed'}
        >
          {entry.environment}
        </span>
      ))}
    </span>
  );
}

/**
 * The table.
 *
 * @param props - See {@link VersionsManageTableProps}.
 * @returns The table.
 */
export function VersionsManageTable({
  slug,
  versions,
  deleted,
  runningIn,
  selected,
  onSelect,
  canTag,
  canDelete,
  onTag,
  onDelete,
  onRestore,
  busy,
}: VersionsManageTableProps) {
  const selectable = canDelete || (canTag && !deleted);
  const allSelected = versions.length > 0 && versions.every((version) => selected.has(version.number));
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table ppx-versions__table" data-testid="ppx-versions-manage-table">
        <caption className="sr-only">
          {deleted ? 'Deleted versions, latest recorded first' : 'Versions, latest recorded first'}
        </caption>
        <thead>
          <tr>
            {selectable ? (
              <th scope="col" className="ppx-versions__select">
                <Checkbox
                  checked={allSelected}
                  onCheckedChange={(on) => onSelect(null, on === true)}
                  aria-label="Select all shown versions"
                  data-testid="ppx-versions-select-all"
                />
              </th>
            ) : null}
            <th scope="col">Version</th>
            <th scope="col">Branch</th>
            <th scope="col">Tags</th>
            <th scope="col">{deleted ? 'Deleted' : 'Running in'}</th>
            <th scope="col">Created</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {versions.map((version) => {
            const number = version.number;
            const running = runningIn?.get(number);
            const rowBusy = busy === number;
            const gone = version as DeletedVersion;
            return (
              <tr
                key={version.id}
                className={deleted ? 'ppx-versions__row--deleted' : undefined}
                data-testid={`ppx-version-row-${number}`}
              >
                {selectable ? (
                  <td className="ppx-versions__select">
                    <Checkbox
                      checked={selected.has(number)}
                      onCheckedChange={(on) => onSelect(number, on === true)}
                      aria-label={`Select ${number}`}
                    />
                  </td>
                ) : null}
                <th scope="row" className="ppx__mono" title={number}>
                  {shortVersion(number)}
                </th>
                <td>
                  {version.branches.length === 0 ? (
                    <span className="ppx__muted">—</span>
                  ) : (
                    <span className="ppx__chips">
                      {version.branches.map((branch) => (
                        <span key={branch} className="ppx-versions__branch ppx__mono">
                          <GitBranch aria-hidden />
                          {branch}
                        </span>
                      ))}
                    </span>
                  )}
                </td>
                <td>
                  <span className="ppx__chips">
                    {version.tags.map((tag) => (
                      <span key={tag} className="ppx-versions__tag">
                        {tag}
                      </span>
                    ))}
                    {canTag && !deleted ? <AddTag number={number} onTag={onTag} disabled={rowBusy} /> : null}
                    {version.tags.length === 0 && !(canTag && !deleted) ? <span className="ppx__muted">—</span> : null}
                  </span>
                </td>
                <td>
                  {deleted ? (
                    <span className="ppx-versions__deleted">
                      {formatWhen(gone.deleted_at)}
                      {deletedBy(gone) ? <span className="ppx__muted"> {deletedBy(gone)}</span> : null}
                      {gone.purge_after ? (
                        <span className="ppx__muted"> · purged {formatWhen(gone.purge_after)}</span>
                      ) : null}
                    </span>
                  ) : (
                    <RunningCell running={running} />
                  )}
                </td>
                <td className="ppx__when">{formatWhen(version.created_at)}</td>
                <td className="ppx-versions__actions">
                  {deleted ? (
                    canDelete ? (
                      restoreBlock(gone) ? (
                        <span className="ppx__meta">{restoreBlock(gone)}</span>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={rowBusy}
                          onClick={() => onRestore(number)}
                          data-testid={`ppx-restore-${number}`}
                        >
                          <Undo2 aria-hidden />
                          {rowBusy ? 'Restoring…' : 'Restore'}
                        </Button>
                      )
                    ) : null
                  ) : (
                    <DropdownMenu.Root>
                      <DropdownMenu.Trigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={rowBusy}
                          aria-label={`Actions for ${number}`}
                          data-testid={`ppx-version-menu-${number}`}
                        >
                          <Ellipsis aria-hidden />
                        </Button>
                      </DropdownMenu.Trigger>
                      <DropdownMenu.Portal>
                        <DropdownMenu.Content className="tnt-menu" sideOffset={4} align="end">
                          <DropdownMenu.Item className={MENU_ITEM_CLASS} asChild>
                            <Link href={versionMatrixHref(slug, number)}>
                              <FileText aria-hidden />
                              Pacts of this version
                            </Link>
                          </DropdownMenu.Item>
                          <DropdownMenu.Item className={MENU_ITEM_CLASS} asChild>
                            <Link href={versionCanIDeployHref(slug, number)}>
                              <Rocket aria-hidden />
                              Can I deploy this?
                            </Link>
                          </DropdownMenu.Item>
                          {canDelete ? (
                            <>
                              <DropdownMenu.Separator className="ppx-versions__menu-sep" />
                              <DropdownMenu.Item
                                className={`${MENU_ITEM_CLASS} ppx-versions__menu-danger`}
                                onSelect={() => onDelete(number)}
                                data-testid={`ppx-delete-version-${number}`}
                              >
                                <Trash2 aria-hidden />
                                Delete version
                                {deleteBlock(number, running) ? <span className="sr-only"> (blocked)</span> : null}
                              </DropdownMenu.Item>
                            </>
                          ) : null}
                        </DropdownMenu.Content>
                      </DropdownMenu.Portal>
                    </DropdownMenu.Root>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

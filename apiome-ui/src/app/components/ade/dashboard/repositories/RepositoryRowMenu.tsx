'use client';

import { useState } from 'react';
import { MoreVertical, Trash2 } from 'lucide-react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/app/components/ui/AlertDialog';
import { Button } from '@/app/components/ui/Button';
import { toast } from 'sonner';
import { cn } from '@lib/utils';

export function RepositoryRowMenu({
  repositoryId,
  label,
  onRemoved,
  triggerClassName,
}: {
  repositoryId: string;
  label: string;
  onRemoved: () => void;
  triggerClassName?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [removeDialogOpen, setRemoveDialogOpen] = useState(false);

  const performDelete = async () => {
    setBusy(true);
    try {
      const res = await fetch(`/api/repositories/${encodeURIComponent(repositoryId)}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      const data = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : res.statusText);
      }
      setRemoveDialogOpen(false);
      toast.success('Repository removed.');
      onRemoved();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not remove repository.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          disabled={busy}
          className={cn(
            'rounded-lg p-1.5 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-100',
            triggerClassName
          )}
          aria-label="Repository actions"
          onClick={(e) => e.stopPropagation()}
        >
          <MoreVertical className="h-4 w-4" aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className="z-50 min-w-[10rem] rounded-lg border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-800"
          sideOffset={4}
          align="end"
        >
          <DropdownMenu.Item
            className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-rose-700 outline-none hover:bg-rose-50 data-[highlighted]:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-900/30 dark:data-[highlighted]:bg-rose-900/30"
            disabled={busy}
            onSelect={() => setRemoveDialogOpen(true)}
          >
            <Trash2 className="h-4 w-4 shrink-0" aria-hidden />
            Remove from list
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>

    <AlertDialog
      open={removeDialogOpen}
      onOpenChange={(open) => {
        if (busy && !open) return;
        setRemoveDialogOpen(open);
      }}
    >
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Remove from this workspace?</AlertDialogTitle>
          <AlertDialogDescription>
            {`Remove "${label}" from this workspace? You can add the repository again later from Add repository.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <Button type="button" variant="destructive" disabled={busy} onClick={() => void performDelete()}>
            {busy ? 'Removing…' : 'Remove from list'}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    </>
  );
}

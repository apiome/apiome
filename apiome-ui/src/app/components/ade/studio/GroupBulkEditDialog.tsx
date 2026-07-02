'use client';

import { useState, useCallback } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/app/components/ui/Dialog';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';

export interface GroupBulkEditTagOption {
  id: string;
  name: string;
  color?: string;
}

export interface GroupBulkEditSubmitPayload {
  descriptionPrefix?: string;
  descriptionSuffix?: string;
  tagId?: string;
  topLevelPropertyReadOnly?: boolean;
}

interface GroupBulkEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groupName: string;
  classCount: number;
  availableTags: GroupBulkEditTagOption[];
  onSubmit: (payload: GroupBulkEditSubmitPayload) => Promise<void>;
}

export default function GroupBulkEditDialog({
  open,
  onOpenChange,
  groupName,
  classCount,
  availableTags,
  onSubmit,
}: GroupBulkEditDialogProps) {
  const [descriptionPrefix, setDescriptionPrefix] = useState('');
  const [descriptionSuffix, setDescriptionSuffix] = useState('');
  const [tagChoice, setTagChoice] = useState<string>('__none__');
  const [readOnlyMode, setReadOnlyMode] = useState<'skip' | 'true' | 'false'>('skip');
  const [submitting, setSubmitting] = useState(false);

  const reset = useCallback(() => {
    setDescriptionPrefix('');
    setDescriptionSuffix('');
    setTagChoice('__none__');
    setReadOnlyMode('skip');
  }, []);

  const handleClose = useCallback(
    (next: boolean) => {
      if (!next) reset();
      onOpenChange(next);
    },
    [onOpenChange, reset]
  );

  const handleApply = useCallback(async () => {
    setSubmitting(true);
    try {
      const payload: GroupBulkEditSubmitPayload = {};
      if (descriptionPrefix.trim()) payload.descriptionPrefix = descriptionPrefix.trim();
      if (descriptionSuffix.trim()) payload.descriptionSuffix = descriptionSuffix.trim();
      if (tagChoice && tagChoice !== '__none__') payload.tagId = tagChoice;
      if (readOnlyMode === 'true') payload.topLevelPropertyReadOnly = true;
      if (readOnlyMode === 'false') payload.topLevelPropertyReadOnly = false;
      await onSubmit(payload);
      reset();
      onOpenChange(false);
    } catch {
      /* Parent shows alert; keep dialog open */
    } finally {
      setSubmitting(false);
    }
  }, [
    descriptionPrefix,
    descriptionSuffix,
    tagChoice,
    readOnlyMode,
    onSubmit,
    reset,
    onOpenChange,
  ]);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Bulk edit classes in &ldquo;{groupName}&rdquo;</DialogTitle>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Apply metadata changes to all {classCount} class{classCount === 1 ? '' : 'es'} in this
            group (top-level properties only for read-only).
          </p>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="bulk-desc-prefix">Description prefix</Label>
            <Input
              id="bulk-desc-prefix"
              value={descriptionPrefix}
              onChange={(e) => setDescriptionPrefix(e.target.value)}
              placeholder="Optional text before existing description"
              disabled={submitting}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="bulk-desc-suffix">Description suffix</Label>
            <Input
              id="bulk-desc-suffix"
              value={descriptionSuffix}
              onChange={(e) => setDescriptionSuffix(e.target.value)}
              placeholder="Optional text after existing description"
              disabled={submitting}
            />
          </div>
          <div className="space-y-2">
            <Label>Assign tag</Label>
            <Select value={tagChoice} onValueChange={setTagChoice} disabled={submitting}>
              <SelectTrigger>
                <SelectValue placeholder="No tag" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">No tag change</SelectItem>
                {availableTags.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Top-level properties read-only</Label>
            <Select
              value={readOnlyMode}
              onValueChange={(v) => setReadOnlyMode(v as 'skip' | 'true' | 'false')}
              disabled={submitting}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="skip">Do not change</SelectItem>
                <SelectItem value="true">Set read-only</SelectItem>
                <SelectItem value="false">Clear read-only</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button type="button" variant="outline" onClick={() => handleClose(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleApply()} disabled={submitting}>
            {submitting ? 'Applying…' : 'Apply to all'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

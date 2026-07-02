'use client';

import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '../../ui/Dialog';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Label } from '../../ui/Label';
import { Textarea } from '../../ui/Textarea';
import { Alert } from '../../ui/Alert';
import { Checkbox } from '../../ui/Checkbox';
import { RadioGroup, RadioGroupItem } from '../../ui/RadioGroup';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../ui/Select';
import { X } from 'lucide-react';
import { cn } from '../../../../../lib/utils';

export interface ClassItem {
  id: string;
  name: string;
  description?: string;
}

type CompositionType = 'none' | 'allOf' | 'anyOf' | 'oneOf';

interface ReferenceDialogProps {
  open: boolean;
  onClose: () => void;
  classes: ClassItem[];
  onSubmit: (referenceData: {
    name: string;
    description: string | null;
    isArray: boolean;
    targetClassId: string | null;
    targetClassIds?: string[];
    compositionType?: CompositionType;
    minItems?: number;
    maxItems?: number;
    uniqueItems?: boolean;
  }) => Promise<void>;
}

export const ReferenceDialog: React.FC<ReferenceDialogProps> = ({
  open,
  onClose,
  classes,
  onSubmit,
}) => {
  const [referenceName, setReferenceName] = useState('');
  const [referenceDescription, setReferenceDescription] = useState('');
  const [isArray, setIsArray] = useState(false);
  const [compositionType, setCompositionType] = useState<CompositionType>('none');
  const [targetClassId, setTargetClassId] = useState<string>('');
  const [targetClassIds, setTargetClassIds] = useState<string[]>([]);
  const [minItems, setMinItems] = useState('');
  const [maxItems, setMaxItems] = useState('');
  const [uniqueItems, setUniqueItems] = useState(false);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [addClassSelectValue, setAddClassSelectValue] = useState<string>('');

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      setReferenceName('');
      setReferenceDescription('');
      setIsArray(false);
      setCompositionType('none');
      setTargetClassId('');
      setTargetClassIds([]);
      setMinItems('');
      setMaxItems('');
      setUniqueItems(false);
      setError('');
      setAddClassSelectValue('');
    }
  }, [open]);

  const handleSubmit = async () => {
    if (!referenceName.trim()) {
      setError('Reference name is required');
      return;
    }

    if (!/^[A-Za-z0-9_]+$/.test(referenceName)) {
      setError('Reference name can only contain letters, numbers, and underscores');
      return;
    }

    if (compositionType !== 'none' && targetClassIds.length === 0) {
      setError(`Please select at least one class for ${compositionType}`);
      return;
    }

    setIsSubmitting(true);
    setError('');

    try {
      await onSubmit({
        name: referenceName,
        description: referenceDescription || null,
        isArray,
        targetClassId: compositionType === 'none' ? (targetClassId || null) : null,
        targetClassIds: compositionType !== 'none' ? targetClassIds : undefined,
        compositionType: compositionType !== 'none' ? compositionType : undefined,
        minItems: minItems ? parseInt(minItems) : undefined,
        maxItems: maxItems ? parseInt(maxItems) : undefined,
        uniqueItems: isArray ? uniqueItems : undefined,
      });

      onClose();
    } catch (err) {
      console.error('Error creating reference:', err);
      setError(err instanceof Error ? err.message : 'An error occurred while creating the reference');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md" showCloseButton={true} aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Create Reference</DialogTitle>
        </DialogHeader>

        {error && (
          <Alert variant="error" className="mb-4">
            {error}
          </Alert>
        )}

        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Create a reference property that links to another class. You can set the target class now or connect it later using the canvas.
        </p>

        <div className="space-y-2 mb-4">
          <Label htmlFor="reference-name">Reference Name</Label>
          <Input
            id="reference-name"
            autoFocus
            type="text"
            value={referenceName}
            onChange={(e) => {
              const filteredValue = e.target.value.replace(/[^A-Za-z0-9_]/g, '');
              setReferenceName(filteredValue);
            }}
            placeholder="e.g. myReference"
            className="w-full"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Only letters, numbers, and underscores are allowed. Suggest camelCase names.
          </p>
        </div>

        <div className="space-y-2 mb-4">
          <Label htmlFor="reference-description">Description</Label>
          <Textarea
            id="reference-description"
            value={referenceDescription}
            onChange={(e) => setReferenceDescription(e.target.value)}
            placeholder="Optional description"
            rows={2}
            className="w-full"
          />
          <p className="text-xs text-gray-500 dark:text-gray-400">Optional description of this reference</p>
        </div>

        <div className="flex items-center gap-2 mb-4">
          <Checkbox
            id="is-array"
            checked={isArray}
            onCheckedChange={(checked) => setIsArray(!!checked)}
          />
          <Label htmlFor="is-array" className="font-normal cursor-pointer">
            Array of references
          </Label>
        </div>

        {isArray && (
          <div className="pl-6 mb-4 space-y-3">
            <p className="text-xs text-gray-500 dark:text-gray-400">Array constraints:</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="min-items">Min Items</Label>
                <Input
                  id="min-items"
                  type="number"
                  min={0}
                  value={minItems}
                  onChange={(e) => setMinItems(e.target.value)}
                  placeholder="0"
                  className="w-full"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="max-items">Max Items</Label>
                <Input
                  id="max-items"
                  type="number"
                  min={0}
                  value={maxItems}
                  onChange={(e) => setMaxItems(e.target.value)}
                  placeholder="—"
                  className="w-full"
                />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="unique-items"
                checked={uniqueItems}
                onCheckedChange={(checked) => setUniqueItems(!!checked)}
              />
              <Label htmlFor="unique-items" className="font-normal cursor-pointer text-sm">
                Unique items (all array elements must be distinct)
              </Label>
            </div>
          </div>
        )}

        <div className="mb-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Reference Type</p>
          <RadioGroup
            value={compositionType}
            onValueChange={(value) => {
              const next = value as CompositionType;
              setCompositionType(next);
              if (next !== 'none') {
                setTargetClassId('');
              } else {
                setTargetClassIds([]);
              }
            }}
            className="space-y-3"
          >
            <RadioGroupItem
              value="none"
              id="type-none"
              className="items-start"
              label={
                <>
                  <span className="block font-medium text-gray-900 dark:text-gray-100">Single Reference</span>
                  <span className="block text-xs text-gray-500 dark:text-gray-400">Reference a single class (can be set now or connected later)</span>
                </>
              }
            />
            <RadioGroupItem
              value="allOf"
              id="type-allOf"
              className="items-start"
              label={
                <>
                  <span className="block font-medium text-gray-900 dark:text-gray-100">allOf (Composition/Inheritance)</span>
                  <span className="block text-xs text-gray-500 dark:text-gray-400">Must satisfy all referenced schemas (solid line, blue)</span>
                </>
              }
            />
            <RadioGroupItem
              value="anyOf"
              id="type-anyOf"
              className="items-start"
              label={
                <>
                  <span className="block font-medium text-gray-900 dark:text-gray-100">anyOf (Union)</span>
                  <span className="block text-xs text-gray-500 dark:text-gray-400">Can satisfy any of the referenced schemas (dashed line, orange)</span>
                </>
              }
            />
            <RadioGroupItem
              value="oneOf"
              id="type-oneOf"
              className="items-start"
              label={
                <>
                  <span className="block font-medium text-gray-900 dark:text-gray-100">oneOf (Exclusive)</span>
                  <span className="block text-xs text-gray-500 dark:text-gray-400">Must satisfy exactly one referenced schema (dotted line, purple)</span>
                </>
              }
            />
          </RadioGroup>
        </div>

        {compositionType === 'none' ? (
          <div className="space-y-2 mb-4">
            <Label id="target-class-label">Target Class (Optional)</Label>
            <Select
              value={targetClassId || '__none__'}
              onValueChange={(v) => setTargetClassId(v === '__none__' ? '' : v)}
            >
              <SelectTrigger aria-labelledby="target-class-label" className="w-full">
                <SelectValue placeholder="No target (set later)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">No target (set later)</SelectItem>
                {classes.map((cls) => (
                  <SelectItem key={cls.id} value={cls.id}>
                    {cls.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Select a class to reference, or leave empty to set later via canvas connections
            </p>
          </div>
        ) : (
          <div className="mb-4 space-y-3">
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Select Classes for {compositionType}
            </p>
            <div className="space-y-2">
              <Label id="add-class-label">Add Class</Label>
              <Select
                value={addClassSelectValue || '__placeholder__'}
                onValueChange={(v) => {
                  if (v && v !== '__placeholder__') {
                    if (!targetClassIds.includes(v)) {
                      setTargetClassIds([...targetClassIds, v]);
                    }
                    setAddClassSelectValue('');
                  }
                }}
              >
                <SelectTrigger aria-labelledby="add-class-label" className="w-full">
                  <SelectValue placeholder="Select a class to add..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__placeholder__">Select a class to add...</SelectItem>
                  {classes
                    .filter((cls) => !targetClassIds.includes(cls.id))
                    .map((cls) => (
                      <SelectItem key={cls.id} value={cls.id}>
                        {cls.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {compositionType === 'allOf' && 'Add all classes that this property must satisfy'}
                {compositionType === 'anyOf' && 'Add classes that this property can satisfy (one or more)'}
                {compositionType === 'oneOf' && 'Add classes that this property must satisfy (exactly one)'}
              </p>
            </div>

            {targetClassIds.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {targetClassIds.map((classId) => {
                  const cls = classes.find((c) => c.id === classId);
                  return cls ? (
                    <span
                      key={classId}
                      className={cn(
                        'inline-flex items-center gap-1 rounded-md border border-indigo-300 dark:border-indigo-600',
                        'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-800 dark:text-indigo-200',
                        'pl-2.5 pr-1 py-1 text-sm font-medium'
                      )}
                    >
                      {cls.name}
                      <button
                        type="button"
                        onClick={() => setTargetClassIds(targetClassIds.filter((id) => id !== classId))}
                        className="rounded p-0.5 hover:bg-indigo-200 dark:hover:bg-indigo-800 transition-colors"
                        aria-label={`Remove ${cls.name}`}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  ) : null;
                })}
              </div>
            )}

            {targetClassIds.length === 0 && (
              <Alert variant="info">
                No classes selected. Add at least one class to create a {compositionType} reference.
              </Alert>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0">
          <Button type="button" variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={isSubmitting}>
            Create Reference
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ReferenceDialog;

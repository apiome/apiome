'use client';

import { useState, useEffect } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { extractObjectPropertyToClass } from '../../../../../lib/db/helper';

interface Props {
  open: boolean;
  onClose: () => void;
  classProperty: any | null;
  existingClassNames: string[];
  onSuccess?: (newClassId: string, newClassName: string) => void;
}

export default function ExtractToClassDialog({
  open,
  onClose,
  classProperty,
  existingClassNames,
  onSuccess
}: Props) {
  const [className, setClassName] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (classProperty && open) {
      const propertyName = classProperty.name || '';
      const defaultName = propertyName.charAt(0).toUpperCase() + propertyName.slice(1);
      setClassName(defaultName);
      setDescription(`Extracted from ${propertyName}`);
      setError('');
    }
  }, [classProperty, open]);

  const validateClassName = (name: string): string | null => {
    if (!name.trim()) return 'Class name is required';
    const nameLower = name.trim().toLowerCase();
    if (existingClassNames.some(existing => existing.toLowerCase() === nameLower)) {
      return `A class named "${name.trim()}" already exists`;
    }
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name.trim())) {
      return 'Class name must start with a letter and contain only letters, numbers, and underscores';
    }
    return null;
  };

  const handleSubmit = async () => {
    if (!classProperty) return;
    const validationError = validateClassName(className);
    if (validationError) {
      setError(validationError);
      return;
    }
    setIsSubmitting(true);
    setError('');
    try {
      const result = await extractObjectPropertyToClass(
        classProperty.id,
        className.trim(),
        description.trim() || null
      );
      const response = JSON.parse(result);
      if (response.success) {
        if (onSuccess) onSuccess(response.newClassId, response.newClassName);
        onClose();
      } else {
        setError(response.error || 'Failed to extract property to class');
      }
    } catch (err: any) {
      setError(err.message || 'An error occurred');
    } finally {
      setIsSubmitting(false);
    }
  };

  const getPropertyTypeDisplay = () => {
    if (!classProperty) return '';
    const propData = typeof classProperty.data === 'string' ? JSON.parse(classProperty.data) : classProperty.data;
    let baseType = propData.type;
    let isNullable = false;
    if (Array.isArray(propData.type)) {
      isNullable = propData.type.includes('null');
      baseType = propData.type.find((t: string) => t !== 'null');
    }
    const nullableSuffix = isNullable ? '?' : '';
    if (baseType === 'array' && propData.items?.type === 'object') return `object[]${nullableSuffix}`;
    return `object${nullableSuffix}`;
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-[10001]" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[10002] w-full max-w-sm bg-white dark:bg-gray-900 rounded-xl shadow-xl p-6 max-h-[90vh] overflow-auto"
        >
          <Dialog.Title className="text-lg font-semibold text-gray-900 dark:text-gray-100">Extract Property to Class</Dialog.Title>

          {error && (
            <div className="mt-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 text-sm">
              {error}
            </div>
          )}

          <div className="mt-4 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 text-blue-800 dark:text-blue-200 text-sm">
            This will create a new class with the object structure and update this property to reference it using <code className="px-1 rounded bg-blue-100 dark:bg-blue-900/50">$ref</code>.
          </div>

          {classProperty && (
            <div className="mt-4 p-4 rounded-lg bg-slate-100 dark:bg-slate-800">
              <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-2">Source Property</p>
              <div className="flex gap-2 items-center mb-1">
                <span className="font-mono text-sm font-medium">{classProperty.name}</span>
                <span className="px-2 py-0.5 rounded text-xs font-mono bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300">
                  {getPropertyTypeDisplay()}
                </span>
              </div>
              {classProperty.description && (
                <p className="text-xs text-slate-500 dark:text-slate-400">{classProperty.description}</p>
              )}
            </div>
          )}

          <label className="block mt-4 text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">New Class Name *</label>
          <input
            type="text"
            autoFocus
            className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 mb-1"
            value={className}
            onChange={(e) => { setClassName(e.target.value); setError(''); }}
            onBlur={() => { const v = validateClassName(className); if (v) setError(v); }}
            disabled={isSubmitting}
          />
          <p className="text-xs text-slate-500 mb-4">Must be unique and start with a letter</p>

          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Description</label>
          <textarea
            className="w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 resize-none"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={isSubmitting}
          />
          <p className="text-xs text-slate-500 mb-4">Optional description for the new class</p>

          <div className="mt-4 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200 text-sm">
            <strong>Note:</strong> After extraction, the original property will reference the new class. Any nested properties will be moved to the new class.
          </div>

          <div className="mt-6 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isSubmitting || !className.trim()}
              className="px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {isSubmitting ? 'Extracting...' : 'Extract to Class'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

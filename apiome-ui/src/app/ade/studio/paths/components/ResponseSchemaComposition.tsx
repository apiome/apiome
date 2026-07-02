'use client';

import React, { useEffect, useMemo, useState } from 'react';
import * as Accordion from '@radix-ui/react-accordion';
import { ChevronDown, GitBranchPlus, Trash2 } from 'lucide-react';
import { Button } from '../../../../components/ui/Button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../../components/ui/Select';
import { updateResponseContentType } from '../../../../../../lib/db/helper-shared-path-responses-content';
import {
  getActiveCompositionKind,
  validateInlineSchemaCompositions,
  type InlineSchema,
} from '../../../../../../lib/utils/inline-schema-utils';

export type CombinatorKind = 'none' | 'allOf' | 'anyOf' | 'oneOf';

interface ClassOption {
  id: string;
  name: string;
}

interface ResponseSchemaCompositionProps {
  contentTypeId: string;
  inlineSchema: InlineSchema | null | undefined;
  classes: ClassOption[];
  isDark: boolean;
  onUpdated: () => void | Promise<void>;
}

function refForClassName(className: string): string {
  return `#/components/schemas/${className}`;
}

function branchesFromSchema(
  schema: InlineSchema | null | undefined,
  kind: CombinatorKind,
  classList: ClassOption[]
): { id: string; classId: string }[] {
  if (!schema || kind === 'none') return [];
  const key = kind as 'allOf' | 'anyOf' | 'oneOf';
  const raw = schema[key];
  if (!Array.isArray(raw)) return [];
  const out: { id: string; classId: string }[] = [];
  for (const item of raw) {
    if (item && typeof item === 'object' && typeof (item as { $ref?: string }).$ref === 'string') {
      const ref = (item as { $ref: string }).$ref;
      const name = ref.split('/').pop() || '';
      let classId = '';
      if (name) {
        const found = classList.find((c) => c.name === name);
        if (found) classId = found.id;
      }
      out.push({ id: crypto.randomUUID(), classId });
    }
  }
  return out;
}

export default function ResponseSchemaComposition({
  contentTypeId,
  inlineSchema,
  classes,
  isDark,
  onUpdated,
}: ResponseSchemaCompositionProps) {
  const activeFromDb = getActiveCompositionKind(inlineSchema ?? null);
  const [combinator, setCombinator] = useState<CombinatorKind>(
    activeFromDb ?? 'none'
  );
  const [branches, setBranches] = useState<{ id: string; classId: string }[]>([]);

  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const classById = useMemo(() => new Map(classes.map((c) => [c.id, c])), [classes]);

  useEffect(() => {
    const k = activeFromDb ?? 'none';
    setCombinator(k);
    setBranches(branchesFromSchema(inlineSchema, k, classes));
  }, [inlineSchema, activeFromDb, classes]);

  const buildInlineBase = (): InlineSchema => {
    const base: InlineSchema = {
      type: 'object',
      properties: Array.isArray(inlineSchema?.properties) ? inlineSchema!.properties! : [],
    };
    if (inlineSchema?.description) base.description = inlineSchema.description;
    return base;
  };

  const applyToDatabase = async () => {
    setError(null);
    const base = buildInlineBase();
    delete (base as { allOf?: unknown }).allOf;
    delete (base as { anyOf?: unknown }).anyOf;
    delete (base as { oneOf?: unknown }).oneOf;

    if (combinator === 'none') {
      const next: InlineSchema = { ...base };
      const errs = validateInlineSchemaCompositions(next);
      if (errs.length > 0) {
        setError(errs[0]);
        return;
      }
      setSaving(true);
      try {
        const result = await updateResponseContentType(contentTypeId, { inlineSchema: next });
        const data = JSON.parse(result);
        if (!data.success) {
          setError(data.error || 'Failed to update');
          return;
        }
        await onUpdated();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to update');
      } finally {
        setSaving(false);
      }
      return;
    }

    const incomplete = branches.some((b) => !b.classId);
    if (incomplete) {
      setError('Select a class for each branch before applying.');
      return;
    }
    if (branches.length === 0) {
      setError('Add at least one branch, or set combinator to None.');
      return;
    }

    const refs = branches.map((b) => {
      const cls = classById.get(b.classId);
      if (!cls?.name) return null;
      return { $ref: refForClassName(cls.name) };
    }).filter(Boolean) as { $ref: string }[];

    const next: InlineSchema = {
      ...base,
      properties: [],
    };
    if (combinator === 'allOf') next.allOf = refs;
    else if (combinator === 'anyOf') next.anyOf = refs;
    else next.oneOf = refs;

    const errs = validateInlineSchemaCompositions(next);
    if (errs.length > 0) {
      setError(errs[0]);
      return;
    }

    setSaving(true);
    try {
      const result = await updateResponseContentType(contentTypeId, { inlineSchema: next });
      const data = JSON.parse(result);
      if (!data.success) {
        setError(data.error || 'Failed to update');
        return;
      }
      await onUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update');
    } finally {
      setSaving(false);
    }
  };

  const propertyCount = Array.isArray(inlineSchema?.properties) ? inlineSchema.properties.length : 0;
  const disabled = propertyCount > 0;

  const handleAddBranch = () => {
    setBranches((prev) => [...prev, { id: crypto.randomUUID(), classId: '' }]);
  };

  const handleRemoveBranch = (id: string) => {
    setBranches((prev) => prev.filter((b) => b.id !== id));
  };

  const handleBranchClass = (id: string, classId: string) => {
    setBranches((prev) => prev.map((b) => (b.id === id ? { ...b, classId } : b)));
  };

  return (
    <div
      className={`mb-6 p-4 rounded-lg border ${
        isDark ? 'border-slate-600 bg-slate-800/40' : 'border-slate-200 bg-slate-50/80'
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <GitBranchPlus className="w-4 h-4 text-indigo-500 shrink-0" />
        <span className="text-sm font-semibold">Schema composition</span>
      </div>
      <p className="text-[11px] text-gray-500 dark:text-gray-400 mb-3">
        Model <code className="text-[10px]">allOf</code>, <code className="text-[10px]">anyOf</code>, or{' '}
        <code className="text-[10px]">oneOf</code> using <code className="text-[10px]">$ref</code> to component
        classes. Excluded while this content type has inline properties.
      </p>

      {disabled && (
        <p className="text-xs text-amber-600 dark:text-amber-400 mb-2">
          Remove inline properties on this content type to use composition.
        </p>
      )}

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400 mb-2" role="alert">
          {error}
        </p>
      )}

      <div className="space-y-2">
        <label className="block text-[11px] font-medium text-gray-600 dark:text-gray-400">
          Combinator
        </label>
        <Select
          value={combinator}
          onValueChange={(v) => {
            setError(null);
            setCombinator(v as CombinatorKind);
            if ((v as CombinatorKind) === 'none') {
              setBranches([]);
            } else if (branches.length === 0) {
              setBranches([{ id: crypto.randomUUID(), classId: '' }]);
            }
          }}
          disabled={disabled || saving}
        >
          <SelectTrigger
            className={`h-9 text-sm ${isDark ? 'border-slate-600' : ''}`}
            aria-label="Schema combinator"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">None</SelectItem>
            <SelectItem value="allOf">allOf</SelectItem>
            <SelectItem value="anyOf">anyOf</SelectItem>
            <SelectItem value="oneOf">oneOf</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {combinator !== 'none' && !disabled && (
        <div className="mt-3 space-y-2">
          <Accordion.Root type="multiple" className="space-y-1">
            {branches.map((branch, index) => (
              <Accordion.Item
                key={branch.id}
                value={branch.id}
                className={`rounded-md border overflow-hidden ${
                  isDark ? 'border-slate-600 bg-slate-900/40' : 'border-slate-200 bg-white'
                }`}
              >
                <Accordion.Header>
                  <Accordion.Trigger
                    className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs font-medium ${
                      isDark ? 'text-slate-200 hover:bg-slate-800' : 'text-slate-800 hover:bg-slate-50'
                    }`}
                  >
                    <span>
                      Branch {index + 1}
                      {branch.classId && classById.get(branch.classId)?.name
                        ? ` — ${classById.get(branch.classId)!.name}`
                        : ''}
                    </span>
                    <ChevronDown className="w-4 h-4 shrink-0 transition-transform data-[state=open]:rotate-180" />
                  </Accordion.Trigger>
                </Accordion.Header>
                <Accordion.Content className="border-t border-slate-200 dark:border-slate-600 px-3 py-2 pb-3 data-[state=open]:animate-in">
                  <div className="flex gap-2 items-start">
                    <Select
                      value={branch.classId || '__pick__'}
                      onValueChange={(v) =>
                        handleBranchClass(branch.id, v === '__pick__' ? '' : v)
                      }
                      disabled={saving}
                    >
                      <SelectTrigger className="h-9 text-xs flex-1" aria-label={`Class for branch ${index + 1}`}>
                        <SelectValue placeholder="Component class" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__pick__">Select class…</SelectItem>
                        {classes.map((c) => (
                          <SelectItem key={c.id} value={c.id} className="text-xs">
                            {c.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-9 px-2 shrink-0"
                      onClick={() => handleRemoveBranch(branch.id)}
                      disabled={saving || branches.length <= 1}
                      aria-label={`Remove branch ${index + 1}`}
                    >
                      <Trash2 className="w-4 h-4 text-red-500" />
                    </Button>
                  </div>
                </Accordion.Content>
              </Accordion.Item>
            ))}
          </Accordion.Root>

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full h-8 text-xs"
            onClick={handleAddBranch}
            disabled={saving}
          >
            Add branch
          </Button>
        </div>
      )}

      {!disabled && (
        <Button
          type="button"
          className="mt-3 w-full h-9 text-sm"
          onClick={() => void applyToDatabase()}
          disabled={saving}
        >
          {saving ? 'Applying…' : 'Apply composition'}
        </Button>
      )}
    </div>
  );
}

'use client';

import { Tag } from 'lucide-react';
import { Input } from '../../../ui/Input';
import { Label } from '../../../ui/Label';
import { Textarea } from '../../../ui/Textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../../ui/Select';
import { filterSlugInput } from '../../../../utils/slug';
import {
  PROJECT_DOMAIN_CATEGORIES,
  PROJECT_DOMAIN_CATEGORY_NONE,
} from '../../../../utils/project-domain-categories';
import type { WizardBasics } from './wizardTypes';

export interface StepBasicsProps {
  value: WizardBasics;
  onChange: (next: WizardBasics) => void;
}

function deriveSlug(name: string): string {
  return filterSlugInput(name.trim().replace(/\s+/g, '-'));
}

export function StepBasics({ value, onChange }: StepBasicsProps) {
  function updateField<K extends keyof WizardBasics>(key: K, next: WizardBasics[K]) {
    onChange({ ...value, [key]: next });
  }

  function handleNameChange(name: string) {
    onChange({
      ...value,
      name,
      slug: value.slugTouched ? value.slug : deriveSlug(name),
    });
  }

  function handleSlugChange(raw: string) {
    onChange({
      ...value,
      slug: filterSlugInput(raw),
      slugTouched: true,
    });
  }

  return (
    <div className="space-y-5">
      <header className="flex items-start gap-3">
        <div className="p-2 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-300">
          <Tag className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-base font-semibold">Project basics</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Identify the project. The slug is used in URLs, CI tokens and published spec
            paths &mdash; it is hard to change later.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-5">
        <div className="space-y-1.5 md:col-span-2">
          <Label htmlFor="wiz-name">
            Name <span className="text-rose-500">*</span>
          </Label>
          <Input
            id="wiz-name"
            value={value.name}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="e.g. Billing API"
            autoFocus
          />
          <p className="text-[11px] text-gray-500">Display name for this project.</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="wiz-slug">
            Slug <span className="text-rose-500">*</span>
          </Label>
          <Input
            id="wiz-slug"
            value={value.slug}
            onChange={(e) => handleSlugChange(e.target.value)}
            placeholder="billing-api"
            className="font-mono"
          />
          <p className="text-[11px] text-amber-600 dark:text-amber-400">
            URL-safe, lowercase, dashes only. Auto-derived from the name unless you edit
            it.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="wiz-domain">Domain category</Label>
          <Select
            value={value.domainCategory}
            onValueChange={(v) => updateField('domainCategory', v)}
          >
            <SelectTrigger id="wiz-domain">
              <SelectValue placeholder="Select a category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={PROJECT_DOMAIN_CATEGORY_NONE}>None</SelectItem>
              {PROJECT_DOMAIN_CATEGORIES.map((cat) => (
                <SelectItem key={cat.id} value={cat.id}>
                  {cat.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[11px] text-gray-500">
            Helps people find related projects in the dashboard.
          </p>
        </div>

        <div className="space-y-1.5 md:col-span-2">
          <Label htmlFor="wiz-description">Description</Label>
          <Textarea
            id="wiz-description"
            rows={3}
            value={value.description}
            onChange={(e) => updateField('description', e.target.value)}
            placeholder="Short description of what this project models or exposes."
          />
          <p className="text-[11px] text-gray-500">
            Shown on the project card and in published docs.
          </p>
        </div>
      </div>
    </div>
  );
}

'use client';

/**
 * Categorize a catalog item — its domain and its tags (MFI-6.3, #3755).
 *
 * Opened from the row menu's **Categorize…** and from the item page's header. The paradigm is
 * shown but not editable: it is derived from the item's latest revision. The domain comes from
 * the same list the Projects pickers use; the tags are free-form, typed and added with Enter
 * (or a comma) and removed with their × button. Every tag is held to the REST API's rule as it
 * is typed (`normalizeCatalogTag`), so a refusal is immediate rather than after a round trip;
 * the API is still the authority and anything it refuses is shown under the field.
 *
 * Saving replaces the item's domain and tags outright (`PUT /api/catalog/{id}/categories`).
 */

import * as React from 'react';
import { X } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/app/components/ui/Select';
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';
import {
  PROJECT_DOMAIN_CATEGORIES,
  PROJECT_DOMAIN_CATEGORY_NONE,
} from '@/app/utils/project-domain-categories';

import { CATALOG_MAX_TAGS, catalogDomainLabel, normalizeCatalogTag } from './catalogModel';

/** What the dialog edits and what a save returns. */
export interface CatalogCategories {
  /** The derived paradigm, shown read-only. */
  paradigm?: string | null;
  /** The domain id, or null for none. */
  domain: string | null;
  /** The tags, lower-cased. */
  tags: string[];
}

export interface CatalogCategoriesDialogProps {
  /** Whether the dialog is showing. Mount it with a fresh `key` per item. */
  open: boolean;
  /** The item being categorized. */
  item: { id: string; name: string } & CatalogCategories;
  /** Called with `false` to close. */
  onOpenChange: (open: boolean) => void;
  /** Called with the saved categorization once the API accepted it. */
  onSaved: (saved: CatalogCategories) => void;
}

const DOMAIN_FIELD_ID = 'catalog-categories-domain';
const TAG_FIELD_ID = 'catalog-categories-tag';

/**
 * Render the categorize dialog. See {@link CatalogCategoriesDialogProps}.
 *
 * @returns The dialog.
 */
export function CatalogCategoriesDialog({
  open,
  item,
  onOpenChange,
  onSaved,
}: CatalogCategoriesDialogProps) {
  const returnFocus = useReturnFocus(open);
  const [domain, setDomain] = React.useState<string>(item.domain ?? PROJECT_DOMAIN_CATEGORY_NONE);
  const [tags, setTags] = React.useState<string[]>([...item.tags]);
  const [draft, setDraft] = React.useState('');
  const [tagError, setTagError] = React.useState<string | null>(null);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  /** Add the typed tag, if it is acceptable and new; say why when it is not. */
  const addDraft = () => {
    if (!draft.trim()) return;
    const result = normalizeCatalogTag(draft);
    if ('error' in result) {
      setTagError(result.error);
      return;
    }
    if (tags.includes(result.tag)) {
      setDraft('');
      setTagError(null);
      return;
    }
    if (tags.length >= CATALOG_MAX_TAGS) {
      setTagError(`A catalog item can carry at most ${CATALOG_MAX_TAGS} tags.`);
      return;
    }
    setTags([...tags, result.tag]);
    setDraft('');
    setTagError(null);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault();
      addDraft();
    } else if (event.key === 'Backspace' && !draft && tags.length > 0) {
      setTags(tags.slice(0, -1));
    }
  };

  const handleSave = async () => {
    // A tag still in the box is meant to be saved, as if Enter had been pressed.
    let nextTags = tags;
    if (draft.trim()) {
      const result = normalizeCatalogTag(draft);
      if ('error' in result) {
        setTagError(result.error);
        return;
      }
      nextTags = tags.includes(result.tag) ? tags : [...tags, result.tag];
    }
    setSaving(true);
    setSaveError(null);
    try {
      const response = await fetch(`/api/catalog/${encodeURIComponent(item.id)}/categories`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain: domain === PROJECT_DOMAIN_CATEGORY_NONE ? null : domain,
          tags: nextTags,
        }),
      });
      const data = (await response.json().catch(() => null)) as
        | (Partial<CatalogCategories> & { success?: boolean; detail?: string; error?: string })
        | null;
      if (!response.ok || !data?.success) {
        setSaveError(data?.detail || data?.error || 'The categories could not be saved.');
        return;
      }
      onSaved({
        paradigm: data.paradigm ?? item.paradigm ?? null,
        domain: data.domain ?? null,
        tags: data.tags ?? nextTags,
      });
      onOpenChange(false);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'The categories could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : undefined)}>
      <DialogContent
        size="sm"
        onCloseAutoFocus={returnFocus}
        data-testid="catalog-categories-dialog"
      >
        <DialogHeader>
          <DialogTitle>Categorize {item.name}</DialogTitle>
          <DialogDescription>
            The domain and tags become filters on the Catalog list. The paradigm comes from the
            imported source and cannot be changed here.
          </DialogDescription>
        </DialogHeader>

        <div className="cat-categories">
          <div className="cat-categories__paradigm" data-testid="catalog-categories-paradigm">
            <span className="cat-categories__term">Paradigm</span>
            <span>{item.paradigm ? item.paradigm : 'Not detected'}</span>
          </div>

          <FormField label="Domain" htmlFor={DOMAIN_FIELD_ID}>
            <Select value={domain} onValueChange={setDomain}>
              <SelectTrigger id={DOMAIN_FIELD_ID} data-testid="catalog-categories-domain">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={PROJECT_DOMAIN_CATEGORY_NONE}>No domain</SelectItem>
                {PROJECT_DOMAIN_CATEGORIES.map((entry) => (
                  <SelectItem key={entry.id} value={entry.id}>
                    {catalogDomainLabel(entry.id)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>

          <FormField
            label="Tags"
            htmlFor={TAG_FIELD_ID}
            helperText={`Press Enter to add a tag. Up to ${CATALOG_MAX_TAGS}; stored in lower case.`}
            error={tagError ?? undefined}
          >
            <div className="cat-categories__tags">
              {tags.length > 0 ? (
                <ul className="cat-tags" aria-label="Tags" data-testid="catalog-categories-tags">
                  {tags.map((tag) => (
                    <li key={tag}>
                      <Badge variant="outline" className="cat-tag">
                        {tag}
                        <button
                          type="button"
                          className="cat-tag__remove"
                          aria-label={`Remove tag ${tag}`}
                          onClick={() => setTags(tags.filter((t) => t !== tag))}
                        >
                          <X aria-hidden />
                        </button>
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : null}
              <Input
                id={TAG_FIELD_ID}
                value={draft}
                placeholder="e.g. payments"
                onChange={(event) => {
                  setDraft(event.target.value);
                  setTagError(null);
                }}
                onKeyDown={handleKeyDown}
                data-testid="catalog-categories-tag-input"
              />
            </div>
          </FormField>

          {saveError ? (
            <div className="cat-categories__error" role="alert">
              {saveError}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" disabled={saving} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={saving}
            onClick={() => void handleSave()}
            data-testid="catalog-categories-save"
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

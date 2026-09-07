'use client';

import * as React from 'react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Input } from '@/app/components/ui/Input';
import { Label } from '@/app/components/ui/Label';
import { Spinner } from '@/app/components/ui/Spinner';
import { Textarea } from '@/app/components/ui/Textarea';

import type { Consumer } from './consumersModel';

/**
 * Register or edit a consumer — CTG-4.1 (#4479).
 *
 * One dialog, two moods, because the fields are the same and the difference is one sentence
 * and one disabled control.
 *
 * ### The handle is fixed after registration
 *
 * `slug` is the name a Pact file and a CI job use. Renaming it would silently orphan every
 * reference — the import that has been filing contracts under `billing-service` for six months
 * would quietly start a second consumer. So in edit mode the field is shown (a person needs to
 * know what the handle *is*) and disabled, with the reason under it. The REST patch model
 * forbids the key outright, so this is a second statement of one rule, not the only one.
 */

/** What the dialog is doing. */
export type ConsumerFormMode = 'create' | 'edit';

/** The editable identity of a consumer. */
export interface ConsumerDraft {
  slug: string;
  name: string;
  description: string;
  owner: string;
  contact: string;
}

/** An empty draft, for a fresh registration. */
export const EMPTY_CONSUMER_DRAFT: ConsumerDraft = {
  slug: '',
  name: '',
  description: '',
  owner: '',
  contact: '',
};

/**
 * The draft that edits an existing consumer.
 *
 * @param consumer The consumer.
 * @returns Its fields as a draft, with nulls flattened to empty strings so the inputs stay
 *   controlled.
 */
export function draftFromConsumer(consumer: Consumer): ConsumerDraft {
  return {
    slug: consumer.slug,
    name: consumer.name,
    description: consumer.description ?? '',
    owner: consumer.owner ?? '',
    contact: consumer.contact ?? '',
  };
}

/** Props for {@link ConsumerFormDialog}. */
export interface ConsumerFormDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** Registering or editing. */
  mode: ConsumerFormMode;
  /** The consumer being edited; `null` in create mode. */
  consumer: Consumer | null;
  /**
   * Save the draft.
   *
   * @param draft What was typed.
   * @returns The error to show inline, or `null` on success.
   */
  onSubmit: (draft: ConsumerDraft) => Promise<string | null>;
}

/**
 * The register / edit dialog.
 *
 * @param props See {@link ConsumerFormDialogProps}.
 * @returns The dialog.
 */
export default function ConsumerFormDialog({
  open,
  onOpenChange,
  mode,
  consumer,
  onSubmit,
}: ConsumerFormDialogProps) {
  const [draft, setDraft] = React.useState<ConsumerDraft>(EMPTY_CONSUMER_DRAFT);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  // Reset on every open rather than on mount: the dialog stays mounted between uses, so a
  // draft left behind by the previous consumer would be the one a new registration starts from.
  React.useEffect(() => {
    if (!open) return;
    setDraft(consumer ? draftFromConsumer(consumer) : EMPTY_CONSUMER_DRAFT);
    setError('');
    setBusy(false);
  }, [open, consumer]);

  const editing = mode === 'edit';
  const canSubmit = draft.name.trim().length > 0 && !busy;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError('');
    const failure = await onSubmit(draft);
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="cns-dialog">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit consumer' : 'Register a consumer'}</DialogTitle>
          <DialogDescription>
            {editing
              ? 'Change who this consumer is and who to reach when its contract would break.'
              : 'Name a client of this project. What it uses is declared separately — by importing a Pact file, or by picking operations.'}
          </DialogDescription>
        </DialogHeader>

        <form className="cns-form" onSubmit={handleSubmit}>
          <div className="cns-form__field">
            <Label htmlFor="consumer-name">Name</Label>
            <Input
              id="consumer-name"
              value={draft.name}
              autoFocus
              maxLength={200}
              placeholder="Billing Service"
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
          </div>

          <div className="cns-form__field">
            <Label htmlFor="consumer-slug">Handle</Label>
            <Input
              id="consumer-slug"
              className="mono"
              value={draft.slug}
              disabled={editing}
              maxLength={128}
              placeholder="billing-service"
              onChange={(event) => setDraft({ ...draft, slug: event.target.value })}
            />
            <p className="cns-form__hint">
              {editing
                ? 'The handle cannot change: Pact files and CI jobs name it, and renaming it would orphan every reference.'
                : 'Lowercase letters, digits and hyphens. Derived from the name when left empty.'}
            </p>
          </div>

          <div className="cns-form__field">
            <Label htmlFor="consumer-owner">Owner</Label>
            <Input
              id="consumer-owner"
              value={draft.owner}
              maxLength={200}
              placeholder="Payments squad"
              onChange={(event) => setDraft({ ...draft, owner: event.target.value })}
            />
            <p className="cns-form__hint">
              The team, channel or person accountable for this consumer.
            </p>
          </div>

          <div className="cns-form__field">
            <Label htmlFor="consumer-contact">Contact</Label>
            <Input
              id="consumer-contact"
              value={draft.contact}
              maxLength={320}
              placeholder="payments@example.com"
              onChange={(event) => setDraft({ ...draft, contact: event.target.value })}
            />
          </div>

          <div className="cns-form__field">
            <Label htmlFor="consumer-description">Description</Label>
            <Textarea
              id="consumer-description"
              value={draft.description}
              rows={3}
              maxLength={4000}
              placeholder="What this client does with the API."
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </div>

          {error && <Alert variant="danger">{error}</Alert>}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {busy && <Spinner className="size-4" />}
              {editing ? 'Save changes' : 'Register consumer'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

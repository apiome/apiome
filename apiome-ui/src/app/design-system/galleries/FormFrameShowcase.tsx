'use client';

/**
 * The §Forms form-frame specimen of the gallery (SUX-2.4, apiome#6752).
 *
 * One two-section form drawn twice: on the page, inside a short scroll well so the sticky
 * footer can be seen staying put while the body scrolls, and inside a `DialogContent`, where
 * the dialog's body scrolls between its header and footer. Typing marks the form dirty;
 * saving with an empty name shows the footer's form-level error. The docs screenshot
 * `design-system-form-frame` is taken of this block.
 */

import * as React from 'react';

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  FormField,
  FormFrame,
  FormSection,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from '@/app/components/ui';

import { SpecimenLabel } from './GallerySection';

/** Props for {@link SpecimenForm}. */
interface SpecimenFormProps {
  /** Prefix for the control ids, so the page and dialog copies do not collide. */
  idPrefix: string;
  /** The header slot. */
  header: React.ReactNode;
  /** Called after a successful save (the dialog copy closes itself). */
  onSaved?: () => void;
  /** Secondary actions for the footer. */
  secondaryActions?: React.ReactNode;
}

/**
 * The specimen form: a "Basics" and an "Access" section.
 *
 * @param props See {@link SpecimenFormProps}.
 * @returns The form.
 */
function SpecimenForm({ idPrefix, header, onSaved, secondaryActions }: SpecimenFormProps) {
  const [name, setName] = React.useState('Payments API');
  const [dirty, setDirty] = React.useState(false);
  const [error, setError] = React.useState<string | undefined>();
  const touch = () => {
    setDirty(true);
    setError(undefined);
  };

  return (
    <FormFrame
      width="narrow"
      header={header}
      submitLabel="Save project"
      dirty={dirty}
      error={error}
      secondaryActions={secondaryActions}
      onSubmit={() => {
        if (!name.trim()) {
          setError('Give the project a name before saving.');
          return;
        }
        setDirty(false);
        onSaved?.();
      }}
    >
      <FormSection title="Basics" description="What the project is called and where it lives.">
        <FormField label="Project name" required htmlFor={`${idPrefix}-name`}>
          <Input
            id={`${idPrefix}-name`}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              touch();
            }}
          />
        </FormField>
        <FormField label="Slug" helperText="Lowercase letters, numbers and dashes." htmlFor={`${idPrefix}-slug`}>
          <Input id={`${idPrefix}-slug`} className="mono" defaultValue="payments-api" onChange={touch} />
        </FormField>
      </FormSection>
      <FormSection title="Access" description="Who can see the project and what it is for.">
        <FormField label="Visibility" htmlFor={`${idPrefix}-visibility`}>
          <Select defaultValue="workspace" onValueChange={touch}>
            <SelectTrigger id={`${idPrefix}-visibility`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="private">Only me</SelectItem>
              <SelectItem value="workspace">Everyone in the workspace</SelectItem>
              <SelectItem value="public">Public</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Description" htmlFor={`${idPrefix}-description`}>
          <Textarea
            id={`${idPrefix}-description`}
            rows={4}
            defaultValue="Card and bank payments for the storefront."
            onChange={touch}
          />
        </FormField>
      </FormSection>
    </FormFrame>
  );
}

/**
 * The form-frame specimen: page context and dialog context.
 *
 * @returns The specimen block.
 */
export function FormFrameShowcase() {
  const [open, setOpen] = React.useState(false);

  return (
    <div data-testid="design-system-form-frame" className="flex flex-col gap-4 border-t border-border pt-4">
      <SpecimenLabel>Form frame — on a page</SpecimenLabel>
      <div className="max-h-96 overflow-y-auto rounded-md bg-surface p-4 shadow-[inset_0_0_0_1px_var(--border)]">
        <SpecimenForm
          idPrefix="ds-ff-page"
          header={
            <div className="flex flex-col gap-1">
              <h3 className="text-base font-semibold text-fg">Project settings</h3>
              <p className="text-sm text-fg-muted">Scroll this well: the footer stays visible.</p>
            </div>
          }
          secondaryActions={<Button variant="ghost">Discard</Button>}
        />
      </div>
      <SpecimenLabel>Form frame — in a dialog</SpecimenLabel>
      <div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button variant="outline">Open the form in a dialog</Button>
          </DialogTrigger>
          <DialogContent>
            <SpecimenForm
              idPrefix="ds-ff-dialog"
              onSaved={() => setOpen(false)}
              header={
                <DialogHeader>
                  <DialogTitle>Project settings</DialogTitle>
                  <DialogDescription>The same form, inside DialogContent.</DialogDescription>
                </DialogHeader>
              }
              secondaryActions={
                <Button variant="ghost" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
              }
            />
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

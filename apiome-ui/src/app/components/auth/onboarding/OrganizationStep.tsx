'use client';

import { useState } from 'react';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { generateTenantSlug, validateTenantSlug } from '@lib/auth/tenant-slug';
import { Button } from '../../ui/Button';
import { FormField } from '../../ui/FormField';
import { Input } from '../../ui/Input';

/** Values the organization step hands back once valid. */
export interface OrganizationStepValues {
  /** Trimmed organization display name. */
  name: string;
  /** Normalized slug (entered, or derived from the name when left blank). */
  slug: string;
}

/** Inputs and callbacks of the organization step. */
export interface OrganizationStepProps {
  /** Name to prefill (from a previous visit to this step). */
  initialName: string;
  /** Slug to prefill (from a previous visit to this step). */
  initialSlug: string;
  /** Return to the welcome step (entered values are kept by the wizard). */
  onBack: () => void;
  /** Advance with validated values. Only called when the form is valid. */
  onContinue: (values: OrganizationStepValues) => void;
}

/**
 * Second wizard step (OLO-4.1): collects the organization name and optional
 * slug. Validation here is the basic shape check shared with the server
 * (`validateTenantSlug`); the live availability check and as-you-type slug
 * suggestion belong to OLO-4.2 (#4206) and extend this component.
 */
export function OrganizationStep({
  initialName,
  initialSlug,
  onBack,
  onContinue,
}: OrganizationStepProps) {
  const [name, setName] = useState(initialName);
  const [slug, setSlug] = useState(initialSlug);
  const [errors, setErrors] = useState<{ name?: string; slug?: string }>({});

  /** Validates the form; on success normalizes values and calls onContinue. */
  const handleContinue = () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setErrors({ name: 'Organization name is required' });
      return;
    }

    const enteredSlug = slug.trim().toLowerCase();
    const effectiveSlug = enteredSlug || generateTenantSlug(trimmedName);
    const slugError = validateTenantSlug(effectiveSlug);
    if (slugError) {
      // With no entered slug the failure came from deriving one, so the name
      // field is the one the user must fix.
      setErrors(
        enteredSlug
          ? { slug: slugError }
          : { name: 'Could not derive a URL slug from this name — please add a slug below' }
      );
      return;
    }

    setErrors({});
    onContinue({ name: trimmedName, slug: effectiveSlug });
  };

  return (
    <div data-testid="onboarding-step-organization">
      <h1
        id="first-tenant-onboarding-title"
        className="text-xl font-bold text-gray-900 dark:text-white"
      >
        Name your organization
      </h1>
      <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
        This becomes your tenant — the workspace your projects and teammates live in.
      </p>
      <form
        className="mt-6 space-y-4 text-left"
        onSubmit={(event) => {
          event.preventDefault();
          handleContinue();
        }}
      >
        <FormField label="Organization name" required error={errors.name}>
          <Input
            autoFocus
            name="organization-name"
            placeholder="Acme, Inc."
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </FormField>
        <FormField
          label="URL slug"
          error={errors.slug}
          helperText="Lowercase letters, numbers, and dashes. Leave blank to generate one from the name."
        >
          <Input
            name="organization-slug"
            placeholder="acme-inc"
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
          />
        </FormField>
        <div className="flex justify-between gap-3 pt-2">
          <Button type="button" variant="outline" onClick={onBack}>
            <ArrowLeft aria-hidden="true" className="h-4 w-4" />
            Back
          </Button>
          <Button type="submit">
            Continue
            <ArrowRight aria-hidden="true" className="h-4 w-4" />
          </Button>
        </div>
      </form>
    </div>
  );
}

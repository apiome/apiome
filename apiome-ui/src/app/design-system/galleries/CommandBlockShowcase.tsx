'use client';

/**
 * The §The same, from anywhere specimens of the gallery (PFX-8.2, #7299).
 *
 * The production counterpart of the `.ct-cli` card in `docs/mockups/contracts/*.html`:
 *
 *   1. A publish form whose block follows the fields as they are typed — the four pills, the
 *      GitHub Action's own inputs, and the broker token only ever as a variable.
 *   2. A webhook whose password and `Authorization` header are written as `$WEBHOOK_…` variables,
 *      with an event and a signing secret the command cannot carry listed under it.
 *   3. An action no command does (editing a saved webhook): every CLI pill says why, REST stays.
 */

import * as React from 'react';

import { CommandBlock, FormField, Input } from '@/app/components/ui';
import { pactCommandSurfaces, tenantPath, unsupportedLines, type PactAction } from '@lib/pact-commands';
import { webhookCommandAction } from '@lib/pact-webhook-command';
import { emptyWebhookForm } from '@lib/pact-webhooks';
import { SpecimenLabel } from './GallerySection';

/** The publish form's fields. */
interface PublishFields {
  version: string;
  branch: string;
  tag: string;
}

/**
 * The publish form as an action.
 *
 * @param fields - The form.
 * @returns The action.
 */
function publishAction(fields: PublishFields): PactAction {
  return {
    verb: 'publish',
    args: [{ value: 'pacts/', actionInput: 'pacts' }],
    options: [
      { flag: '--consumer-app-version', value: fields.version, actionInput: 'version' },
      { flag: '--branch', value: fields.branch, actionInput: 'branch' },
      { flag: '--tag', value: fields.tag ? [fields.tag] : [], actionInput: 'tags' },
    ],
    rest: {
      method: 'POST',
      path: tenantPath('acme', '/pact-broker/contracts/publish'),
      body: {
        pacticipantName: 'Orders UI',
        pacticipantVersionNumber: fields.version,
        branch: fields.branch || undefined,
        tags: fields.tag ? [fields.tag] : [],
        contracts: ['…'],
      },
    },
  };
}

/** A webhook with every kind of secret, and two values the command cannot carry. */
const WEBHOOK_FORM = {
  ...emptyWebhookForm(),
  url: 'https://ci.example.com/hooks/pact',
  headers: 'Content-Type: application/json\nAuthorization: Bearer s3cr3t-token-value',
  username: 'ci-bot',
  password: 'hunter2-hunter2',
  provider: 'Billing Service',
  events: ['contract_requiring_verification_published', 'contract_became_stale'],
  signingSecret: 'a-signing-secret-of-16+',
};

export function CommandBlockShowcase() {
  const [fields, setFields] = React.useState<PublishFields>({ version: '3.4.0+a1c9e02', branch: 'feature/credit-notes', tag: 'dev' });
  const publish = publishAction(fields);
  const webhook = webhookCommandAction(WEBHOOK_FORM, { tenant: 'acme' });
  const edit = webhookCommandAction(WEBHOOK_FORM, { tenant: 'acme', webhookId: '6f0c2d1e-7a3b-4c55-9d1e-2b3c4d5e6f70' });

  const field = (key: keyof PublishFields) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setFields((current) => ({ ...current, [key]: event.target.value }));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <SpecimenLabel>Follows the form — type in a field</SpecimenLabel>
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField label="Consumer version" htmlFor="cb-version">
            <Input id="cb-version" value={fields.version} onChange={field('version')} />
          </FormField>
          <FormField label="Branch" htmlFor="cb-branch">
            <Input id="cb-branch" value={fields.branch} onChange={field('branch')} />
          </FormField>
          <FormField label="Tag" htmlFor="cb-tag">
            <Input id="cb-tag" value={fields.tag} onChange={field('tag')} />
          </FormField>
        </div>
        <CommandBlock
          surfaces={pactCommandSurfaces(publish)}
          footnote="Version and branch default to the commit and branch of the run in CI."
          data-testid="gallery-command-block-publish"
        />
      </div>
      <div className="flex flex-col gap-3">
        <SpecimenLabel>Secrets as variables, and what the command cannot carry</SpecimenLabel>
        <CommandBlock
          surfaces={pactCommandSurfaces(webhook)}
          unsupported={unsupportedLines(webhook)}
          data-testid="gallery-command-block-webhook"
        />
      </div>
      <div className="flex flex-col gap-3">
        <SpecimenLabel>No command does this — REST only</SpecimenLabel>
        <CommandBlock surfaces={pactCommandSurfaces(edit)} defaultSurface="apiome" data-testid="gallery-command-block-edit" />
      </div>
    </div>
  );
}

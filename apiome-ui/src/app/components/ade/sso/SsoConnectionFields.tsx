'use client';

import * as React from 'react';

import { FormField, Input, RadioGroup, RadioGroupItem, Textarea } from '@/app/components/ui';
import type { RoleRecord } from '@/app/components/ade/access/accessApi';
import { SSO_OWNER_ROLE_SLUG, type WorkspaceSsoEdit } from '@lib/workspace-sso';

/** Props for {@link SsoConnectionFields}. */
export interface SsoConnectionFieldsProps {
  /** Prefix for the fields' ids, unique per form on the page. */
  idPrefix: string;
  /** Which protocol's fields to draw. */
  protocol: 'oidc' | 'saml';
  /**
   * `create` asks for everything the protocol needs; `edit` treats the secrets and the SAML
   * metadata as "leave blank to keep what is stored", since neither is ever read back.
   */
  mode: 'create' | 'edit';
  /** The form's values. */
  values: WorkspaceSsoEdit;
  /** Set one value. */
  onChange: <K extends keyof WorkspaceSsoEdit>(key: K, value: WorkspaceSsoEdit[K]) => void;
  /** The workspace's roles, for the default-role choice. */
  roles: readonly RoleRecord[];
  /** Disables every field while a save is in flight. */
  disabled?: boolean;
  /** For `edit`: whether a client secret / SP key is stored, to say so beside the blank field. */
  stored?: { clientSecret: boolean; spPrivateKey: boolean };
}

/**
 * The settings of an identity-provider connection that the add dialog and the drawer's Configure
 * tab have in common (EID-1.2, #5012): the name, the protocol's own fields — client ID and secret
 * for OIDC; metadata, where the email comes from and the optional signing key for SAML — and the
 * role a member gets on first sign-in.
 *
 * @param props See {@link SsoConnectionFieldsProps}.
 * @returns The fields.
 */
export function SsoConnectionFields({
  idPrefix,
  protocol,
  mode,
  values,
  onChange,
  roles,
  disabled = false,
  stored,
}: SsoConnectionFieldsProps) {
  const id = (name: string) => `${idPrefix}-${name}`;
  const editing = mode === 'edit';
  const keepHint = (what: string, has: boolean | undefined) =>
    has ? `${what} is stored. Leave blank to keep it.` : `No ${what.toLowerCase()} is stored.`;

  return (
    <>
      {protocol === 'oidc' ? (
        <div className="wsso-grid">
          <FormField label="Client ID" htmlFor={id('client-id')} required>
            <Input
              id={id('client-id')}
              className="mono"
              value={values.clientId}
              required
              disabled={disabled}
              autoComplete="off"
              onChange={(event) => onChange('clientId', event.target.value)}
            />
          </FormField>
          <FormField
            label="Client secret"
            htmlFor={id('client-secret')}
            required={!editing}
            helperText={
              editing
                ? keepHint('A client secret', stored?.clientSecret)
                : 'Stored encrypted. It is never shown again.'
            }
          >
            <Input
              id={id('client-secret')}
              type="password"
              className="mono"
              value={values.clientSecret}
              required={!editing}
              disabled={disabled}
              autoComplete="off"
              onChange={(event) => onChange('clientSecret', event.target.value)}
            />
          </FormField>
        </div>
      ) : (
        <>
          <FormField
            label="IdP metadata URL"
            htmlFor={id('metadata-url')}
            helperText={
              editing
                ? 'Leave both metadata fields blank to keep what is stored.'
                : 'Or paste the metadata XML below.'
            }
          >
            <Input
              id={id('metadata-url')}
              type="url"
              value={values.metadataUrl}
              disabled={disabled}
              placeholder="https://idp.example.com/saml/metadata"
              onChange={(event) => onChange('metadataUrl', event.target.value)}
            />
          </FormField>
          <FormField label="IdP metadata XML" htmlFor={id('metadata-xml')}>
            <Textarea
              id={id('metadata-xml')}
              rows={4}
              spellCheck={false}
              className="mono"
              value={values.metadataXml}
              disabled={disabled}
              onChange={(event) => onChange('metadataXml', event.target.value)}
            />
          </FormField>
          <fieldset className="wsso-fieldset" disabled={disabled}>
            <legend className="wsso-legend">Email address comes from</legend>
            <RadioGroup
              className="wsso-radios"
              value={values.emailSource}
              onValueChange={(next) => onChange('emailSource', next === 'attribute' ? 'attribute' : 'nameid')}
            >
              <RadioGroupItem name={id('email-source')} value="nameid" label="The NameID" />
              <RadioGroupItem name={id('email-source')} value="attribute" label="An attribute" />
            </RadioGroup>
          </fieldset>
          {values.emailSource === 'attribute' ? (
            <FormField label="Email attribute name" htmlFor={id('email-attribute')} required>
              <Input
                id={id('email-attribute')}
                className="mono"
                value={values.emailAttribute}
                required
                disabled={disabled}
                placeholder="email"
                onChange={(event) => onChange('emailAttribute', event.target.value)}
              />
            </FormField>
          ) : null}
          <FormField
            label="SP signing key (optional)"
            htmlFor={id('sp-key')}
            helperText={
              editing
                ? keepHint('A signing key', stored?.spPrivateKey)
                : 'A PEM private key, only if your IdP requires signed sign-in requests. Stored encrypted.'
            }
          >
            <Textarea
              id={id('sp-key')}
              rows={3}
              spellCheck={false}
              autoComplete="off"
              className="mono"
              value={values.spPrivateKey}
              disabled={disabled}
              onChange={(event) => onChange('spPrivateKey', event.target.value)}
            />
          </FormField>
        </>
      )}

      <FormField
        label="Default role"
        htmlFor={id('default-role')}
        helperText="The role a member gets the first time they sign in through this provider."
      >
        <select
          id={id('default-role')}
          className="hive-control wsso-select"
          value={values.defaultRole}
          disabled={disabled}
          onChange={(event) => onChange('defaultRole', event.target.value)}
        >
          <option value="">Workspace default</option>
          {roles
            .filter((role) => role.slug !== SSO_OWNER_ROLE_SLUG)
            .map((role) => (
              <option key={role.id} value={role.slug}>
                {role.name}
              </option>
            ))}
        </select>
      </FormField>
    </>
  );
}

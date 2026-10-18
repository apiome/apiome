'use client';

import * as React from 'react';

import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/app/components/ui/Select';
import { Textarea } from '@/app/components/ui/Textarea';
import type { ConnectorField, FieldValues } from '@lib/connector-kinds';

/** The select value meaning "not set" (a Radix select item cannot have an empty value). */
const UNSET = '__unset__';

/**
 * A connector kind's scope or credential fields (CDG-1.7, #5958).
 *
 * Drawn from the kind model (`@lib/connector-kinds`), so the add wizard and the settings tab show the
 * same fields. A `secret` field is a password input (or a textarea for a pasted key file) and is never
 * pre-filled: REST never returns a stored credential.
 *
 * @param props.fields - The fields to draw.
 * @param props.values - The current values.
 * @param props.onChange - Called with the field key and its new value.
 * @param props.idPrefix - Prefix for the inputs' ids (unique per form).
 */
export function ConnectorFields({
  fields,
  values,
  onChange,
  idPrefix,
}: {
  fields: readonly ConnectorField[];
  values: FieldValues;
  onChange: (key: string, value: string | boolean) => void;
  idPrefix: string;
}) {
  return (
    <div className="cnx-fields">
      {fields.map((field) => {
        const id = `${idPrefix}-${field.key}`;
        const value = values[field.key];
        if (field.type === 'boolean') {
          return (
            <label key={field.key} className="cnx-check" htmlFor={id}>
              <input
                id={id}
                type="checkbox"
                checked={value === true}
                onChange={(event) => onChange(field.key, event.target.checked)}
                data-testid={id}
              />
              <span>{field.label}</span>
            </label>
          );
        }
        return (
          <FormField
            key={field.key}
            label={field.label}
            htmlFor={id}
            required={field.required}
            helperText={field.help}
          >
            {field.type === 'select' ? (
              <Select
                value={typeof value === 'string' && value ? value : UNSET}
                onValueChange={(next) => onChange(field.key, next === UNSET ? '' : next)}
              >
                <SelectTrigger id={id} data-testid={id}>
                  <SelectValue placeholder="Choose" />
                </SelectTrigger>
                <SelectContent>
                  {field.required ? null : <SelectItem value={UNSET}>Default</SelectItem>}
                  {(field.options ?? []).map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : field.type === 'secret' && field.multiline ? (
              <Textarea
                id={id}
                value={typeof value === 'string' ? value : ''}
                onChange={(event) => onChange(field.key, event.target.value)}
                rows={6}
                spellCheck={false}
                autoComplete="off"
                data-testid={id}
              />
            ) : (
              <Input
                id={id}
                type={field.type === 'secret' ? 'password' : 'text'}
                value={typeof value === 'string' ? value : ''}
                placeholder={field.placeholder}
                onChange={(event) => onChange(field.key, event.target.value)}
                autoComplete={field.type === 'secret' ? 'new-password' : 'off'}
                data-testid={id}
              />
            )}
          </FormField>
        );
      })}
    </div>
  );
}

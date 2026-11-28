'use client';

/**
 * A pacticipant text field with the workspace's names as suggestions (PFX-8.18, #7315). Free text
 * is kept: REST resolves a handle, an id or a name, and a pacticipant beyond the first page of
 * suggestions can still be typed.
 */

import * as React from 'react';
import { Input, Label } from '@/app/components/ui';

/** Props of {@link PacticipantField}. */
export interface PacticipantFieldProps {
  id: string;
  label: string;
  value: string;
  /** Suggested names. */
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function PacticipantField({ id, label, value, options, onChange, disabled, placeholder }: PacticipantFieldProps) {
  return (
    <div className="ppub-field">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} list={`${id}-names`} value={value} disabled={disabled} placeholder={placeholder ?? 'A pacticipant’s name or handle'} onChange={(event) => onChange(event.target.value)} />
      <datalist id={`${id}-names`}>
        {options.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
    </div>
  );
}

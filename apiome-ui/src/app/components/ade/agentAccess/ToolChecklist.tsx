'use client';

import * as React from 'react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Checkbox } from '@/app/components/ui/Checkbox';

import { toggleName } from './agentAccessModel';

/**
 * A checklist of MCP tool names — the allowlist picker — AGX-3.4 (#4540).
 *
 * Shared by the create-key dialog and the edit-allowlist dialog, so a key's tools are chosen the
 * same way in both. The choices are the toolset's **enabled** tools; names already in a key's
 * allowlist that the toolset no longer exposes are listed after them, marked *not exposed*, so
 * the reader can keep or drop them knowingly instead of losing them silently.
 */

/** Props for {@link ToolChecklist}. */
export interface ToolChecklistProps {
  /** The tool names that can be chosen (the toolset's enabled tools). */
  choices: readonly string[];
  /** Names in the selection that are not among the choices. */
  inactive?: readonly string[];
  /** The selected names. */
  value: readonly string[];
  /** Report a new selection. */
  onChange: (next: string[]) => void;
  /** Disable every control. */
  disabled?: boolean;
  /** The id of the element that labels the group. */
  labelledBy: string;
  /** Prefix for each checkbox's id. */
  idPrefix: string;
}

/**
 * The checklist.
 *
 * @param props See {@link ToolChecklistProps}.
 * @returns The list, with select-all / clear actions; an explanatory line when there is nothing
 *   to choose.
 */
export default function ToolChecklist({
  choices,
  inactive = [],
  value,
  onChange,
  disabled = false,
  labelledBy,
  idPrefix,
}: ToolChecklistProps) {
  const selected = React.useMemo(() => new Set(value), [value]);

  if (choices.length === 0 && inactive.length === 0) {
    return (
      <p className="agx-hint" data-testid="agx-tool-checklist-empty">
        This toolset exposes no tools yet. Enable some in the toolset editor first.
      </p>
    );
  }

  const rows = [
    ...choices.map((name) => ({ name, exposed: true })),
    ...inactive.map((name) => ({ name, exposed: false })),
  ];

  return (
    <div className="agx-checklist" data-testid="agx-tool-checklist">
      <div className="agx-checklist__actions">
        <span className="agx-hint">
          {value.length} of {choices.length} selected
        </span>
        {/* `type="button"`: the checklist sits inside the create dialog's form, and a bare
            button there would submit it. */}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={() => onChange([...new Set([...value, ...choices])].sort())}
        >
          Select all
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={() => onChange([])}
        >
          Clear
        </Button>
      </div>
      <ul className="agx-checklist__list" role="group" aria-labelledby={labelledBy}>
        {rows.map(({ name, exposed }) => {
          const id = `${idPrefix}-${name}`;
          return (
            <li key={name} className="agx-checklist__row">
              <Checkbox
                id={id}
                checked={selected.has(name)}
                disabled={disabled}
                onCheckedChange={(checked) => onChange(toggleName(value, name, checked === true))}
              />
              <label htmlFor={id} className="agx-checklist__name mono">
                {name}
              </label>
              {!exposed && <Badge status="disabled">Not exposed</Badge>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

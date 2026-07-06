'use client';

import type { OptionField } from './exportTargetCatalog';

export interface ExportOptionsFormProps {
  /** The selected target's key, used to namespace input ids/names. */
  targetKey: string;
  /** The rendered option fields from `optionFieldsFromSchema`. */
  fields: OptionField[];
  /** Current values keyed by option key. */
  values: Record<string, unknown>;
  /** Per-field validation errors keyed by option key (from `validateExportOptions`), if any. */
  errors?: Record<string, string>;
  /** Update one option's value. */
  onChange: (key: string, value: unknown) => void;
}

/**
 * ExportOptionsForm — the generated per-emitter options form (MFX-1.4), shared by the
 * ExportDialog (MFX-6.1, #3855) and the Export Studio (MFX-41.1, #4348).
 *
 * Renders one control per primitive option field the target's JSON Schema exposes: a checkbox
 * for booleans, a segmented button row for string enums, and a text input for free strings.
 * Complex option types never reach here — `optionFieldsFromSchema` already filters them out, so
 * the emit request leaves them at their server-side defaults. A field's validation error (from
 * `validateExportOptions`) renders inline beneath its control.
 */
export function ExportOptionsForm({
  targetKey,
  fields,
  values,
  errors,
  onChange,
}: ExportOptionsFormProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields.map((field) => (
        <ExportOptionControl
          key={field.key}
          targetKey={targetKey}
          field={field}
          value={values[field.key]}
          error={errors?.[field.key]}
          onChange={(value) => onChange(field.key, value)}
        />
      ))}
    </div>
  );
}

interface ExportOptionControlProps {
  /** The selected target's key, used to namespace input ids/names. */
  targetKey: string;
  field: OptionField;
  value: unknown;
  /** The field's validation error message, when the value is invalid. */
  error?: string;
  onChange: (value: unknown) => void;
}

/**
 * One per-target option control (MFX-1.4): a checkbox for booleans, a segmented button row for
 * string enums, and a text input for free strings. Complex option types never reach here —
 * `optionFieldsFromSchema` already filters them out.
 */
export function ExportOptionControl({ targetKey, field, value, error, onChange }: ExportOptionControlProps) {
  const inputId = `export-option-${targetKey}-${field.key}`;
  const errorId = `${inputId}-error`;
  const errorNote = error ? (
    <p id={errorId} className="mt-1 text-xs text-rose-600 dark:text-rose-400">
      {error}
    </p>
  ) : null;

  if (field.kind === 'boolean') {
    return (
      <div>
        <label className="flex items-start gap-3 text-sm text-gray-700 dark:text-gray-200" htmlFor={inputId}>
          <input
            id={inputId}
            type="checkbox"
            checked={value === true}
            onChange={(e) => onChange(e.target.checked)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className="mt-0.5"
          />
          <span>
            <span className="block font-medium">{field.label}</span>
            {field.description && (
              <span className="block text-xs text-gray-500 dark:text-gray-400">{field.description}</span>
            )}
          </span>
        </label>
        {errorNote}
      </div>
    );
  }

  if (field.kind === 'enum') {
    return (
      <div className="text-sm">
        <div className="font-medium text-gray-700 dark:text-gray-200">{field.label}</div>
        {field.description && (
          <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{field.description}</div>
        )}
        <div className="mt-2 inline-flex overflow-hidden rounded-lg border border-gray-300 dark:border-gray-700">
          {field.enumValues.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onChange(option)}
              className={`px-3 py-1.5 text-xs transition ${
                value === option
                  ? 'bg-indigo-600 font-medium text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50 dark:bg-gray-950 dark:text-gray-200 dark:hover:bg-gray-900'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
        {errorNote}
      </div>
    );
  }

  return (
    <div className="text-sm">
      <label className="font-medium text-gray-700 dark:text-gray-200" htmlFor={inputId}>
        {field.label}
      </label>
      {field.description && (
        <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{field.description}</div>
      )}
      <input
        id={inputId}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        placeholder={field.required ? 'required' : 'server default'}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className="mt-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950"
      />
      {errorNote}
    </div>
  );
}

export default ExportOptionsForm;

/**
 * Pure model for deprecating a registry type (#3482).
 *
 * Backs the Deprecate dialog on the type-detail page. Everything here is side-effect free so the
 * form's validation and request body stay aligned with the lifecycle API
 * (`POST /v1/primitives/{tenant}/{id}/deprecate`, `primitives_lifecycle_routes.py`) and can be
 * unit-tested without React.
 *
 * Deprecation is advisory: a deprecated type still resolves, validates and can be bound. The
 * record is a sunset date, a message and a replacement type — all optional.
 */

/** Longest message the API accepts. Mirrors `MAX_MESSAGE_LENGTH` in `primitives_lifecycle.py`. */
export const MAX_DEPRECATION_MESSAGE = 500;

/** The fields of the Deprecate dialog. */
export interface DeprecateFormData {
  /** `YYYY-MM-DD`, or `''` when no sunset date is set. */
  sunsetDate: string;
  /** Why the type is deprecated and what to do instead. */
  message: string;
  /** Id of the type to use instead, or `''` for none. */
  replacementId: string;
}

/** Field-keyed validation errors (empty object means valid). */
export type DeprecateFormErrors = Partial<Record<keyof DeprecateFormData, string>>;

/** What the form needs to know of the type it edits. */
export interface DeprecationRecord {
  sunset_date?: string | null;
  deprecation_message?: string | null;
  replacement_id?: string | null;
}

/**
 * The form for a type: empty for an active one, pre-filled for one already deprecated (so the
 * dialog doubles as "change the details").
 *
 * @param record The type's current deprecation record.
 * @returns The form's initial values.
 */
export function deprecateFormFrom(record: DeprecationRecord): DeprecateFormData {
  return {
    sunsetDate: record.sunset_date ?? '',
    message: record.deprecation_message ?? '',
    replacementId: record.replacement_id ?? '',
  };
}

/**
 * Today's date in UTC as `YYYY-MM-DD` — the day the API compares a sunset date against.
 *
 * @param now The current instant (injectable for tests).
 * @returns The UTC calendar date.
 */
export function todayIsoDate(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/**
 * Validate the Deprecate form.
 *
 * @param form The current values.
 * @param today Today's UTC date, `YYYY-MM-DD`.
 * @returns A field-keyed error map; empty when the form can be sent.
 */
export function validateDeprecateForm(form: DeprecateFormData, today: string): DeprecateFormErrors {
  const errors: DeprecateFormErrors = {};

  const sunset = form.sunsetDate.trim();
  if (sunset) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(sunset) || Number.isNaN(Date.parse(`${sunset}T00:00:00Z`))) {
      errors.sunsetDate = 'Enter a date as YYYY-MM-DD.';
    } else if (sunset < today) {
      // ISO dates order as strings, so no parsing is needed to compare them.
      errors.sunsetDate = 'The sunset date cannot be in the past.';
    }
  }

  if (form.message.trim().length > MAX_DEPRECATION_MESSAGE) {
    errors.message = `Keep the message to ${MAX_DEPRECATION_MESSAGE} characters or fewer.`;
  }

  return errors;
}

/** Request body for `POST /api/primitives/{id}/deprecate`. */
export interface DeprecateRequestBody {
  sunset_date: string | null;
  message: string | null;
  replacement_id: string | null;
}

/**
 * Build the request body. A blank field is sent as `null`, which clears that detail on a type
 * that is already deprecated.
 *
 * @param form The validated form.
 * @returns The body to send.
 */
export function buildDeprecateRequestBody(form: DeprecateFormData): DeprecateRequestBody {
  return {
    sunset_date: form.sunsetDate.trim() || null,
    message: form.message.trim() || null,
    replacement_id: form.replacementId || null,
  };
}

/** A type as the replacement picker needs it. */
export interface ReplacementCandidate {
  id: string;
  name: string;
  namespace?: string | null;
  deprecated?: boolean;
  deprecated_at?: string | null;
}

/** One option of the replacement picker. */
export interface ReplacementOption {
  id: string;
  /** `name — namespace`, or just the name for a type with no namespace. */
  label: string;
}

/**
 * The types that may replace a deprecated one: every visible type except the type itself and
 * the ones that are themselves deprecated (the API refuses both).
 *
 * @param types The types visible to the tenant.
 * @param selfId The id of the type being deprecated.
 * @returns The options, by name then namespace.
 */
export function replacementOptions(
  types: readonly ReplacementCandidate[],
  selfId: string
): ReplacementOption[] {
  return types
    .filter((type) => type.id !== selfId && !type.deprecated && !type.deprecated_at)
    .map((type) => ({
      id: type.id,
      label: type.namespace ? `${type.name} — ${type.namespace}` : type.name,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

'use client';

/**
 * ResolvedTypePreview (#3476).
 *
 * Given a property's persisted type binding (`$ref` + resolved `primitive_id`,
 * #3475), resolve it to the primitive's *effective* JSON Schema and display the
 * resolved type, format and constraints, plus a live example-value validator
 * (AJV 2020-12). Used by the Designer's class-property editor; reusable in the
 * Paths editor since it only needs the binding identifiers (or a schema).
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Link2, Loader2, CheckCircle2, XCircle, FlaskConical } from 'lucide-react';
import { Input } from '../../ui/Input';
import {
  summarizeEffectiveSchema,
  validateExampleAgainstSchema,
} from './resolvedTypeModel';

export interface ResolvedTypePreviewProps {
  /** The bound registry `$ref` (e.g. `std/v0/types/date`) — shown as the binding chip. */
  propertyRef?: string | null;
  /** The resolved primitive id (FK) used to fetch the effective schema. */
  primitiveId?: string | null;
  /**
   * A pre-resolved effective schema. When supplied the component skips the
   * fetch (useful for Paths/tests where the schema is already in hand).
   */
  schema?: Record<string, unknown> | null;
  className?: string;
}

interface PrimitiveLite {
  name?: string;
  namespace?: string | null;
  schema?: Record<string, unknown>;
}

/**
 * Resolve and render a bound property's effective type. Renders nothing when the
 * property has no registry binding (no `$ref`, no `primitiveId`, no schema).
 */
export const ResolvedTypePreview: React.FC<ResolvedTypePreviewProps> = ({
  propertyRef,
  primitiveId,
  schema: providedSchema,
  className,
}) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetched, setFetched] = useState<PrimitiveLite | null>(null);
  const [example, setExample] = useState('');

  const hasBinding = Boolean(providedSchema || primitiveId || (propertyRef && propertyRef.trim()));

  // Resolve the effective schema by fetching the primitive by its FK so the
  // preview survives a reload (where only the stored ids are available). A
  // directly-provided schema short-circuits the fetch (handled below).
  useEffect(() => {
    if (providedSchema || !primitiveId) {
      setFetched(null);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;

    const resolvePrimitive = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/primitives/${primitiveId}`);
        if (!res.ok) throw new Error('Failed to resolve bound type');
        const data = await res.json();
        if (cancelled) return;
        if (data.success && data.primitive) {
          setFetched(data.primitive as PrimitiveLite);
        } else {
          setError(data.error || 'Bound type could not be resolved');
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to resolve bound type');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    resolvePrimitive();

    return () => {
      cancelled = true;
    };
  }, [providedSchema, primitiveId]);

  // A directly-provided schema wins; otherwise use the fetched primitive.
  const resolved: PrimitiveLite | null = providedSchema ? { schema: providedSchema } : fetched;
  const effectiveSchema = resolved?.schema;
  const summary = useMemo(
    () => (effectiveSchema ? summarizeEffectiveSchema(effectiveSchema) : null),
    [effectiveSchema],
  );

  // Validate the example only when there is something to validate against.
  const validation = useMemo(() => {
    if (!effectiveSchema || example.trim() === '') return null;
    return validateExampleAgainstSchema(example, effectiveSchema);
  }, [effectiveSchema, example]);

  if (!hasBinding) return null;

  const resolvedRef =
    propertyRef ||
    (resolved?.namespace && resolved?.name
      ? `${resolved.namespace.replace(/\/+$/, '')}/${resolved.name}`
      : undefined);

  return (
    <div
      className={`rounded-xl border border-teal-200 bg-teal-50/60 p-4 dark:border-teal-900/50 dark:bg-teal-950/30 ${className || ''}`}
      data-testid="resolved-type-preview"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
          <Link2 className="h-4 w-4 text-teal-500" />
          Resolved Type
        </h4>
        {resolvedRef && (
          <span className="inline-flex items-center gap-1.5 rounded-md border border-teal-200 bg-white px-2 py-1 font-mono text-xs text-teal-700 dark:border-teal-800 dark:bg-teal-900/30 dark:text-teal-300">
            {resolvedRef}
          </span>
        )}
      </div>

      {loading && (
        <div className="mt-3 flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Resolving bound type…
        </div>
      )}

      {!loading && error && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}

      {!loading && !error && summary && (
        <>
          {/* Effective type + format */}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded-md bg-teal-100 px-2 py-1 font-mono text-xs font-medium text-teal-800 dark:bg-teal-900/40 dark:text-teal-200">
              {summary.type}
            </span>
            {summary.format && (
              <span className="inline-flex items-center rounded-md bg-sky-100 px-2 py-1 font-mono text-xs text-sky-700 dark:bg-sky-900/40 dark:text-sky-300">
                format: {summary.format}
              </span>
            )}
          </div>

          {/* Constraints */}
          {summary.constraints.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {summary.constraints.map((c) => (
                <span
                  key={c.label}
                  className="inline-flex items-center rounded bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700"
                >
                  {c.label}: {c.value}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              No additional constraints.
            </p>
          )}

          {/* Example value validation */}
          <div className="mt-4">
            <label
              htmlFor="resolved-type-example"
              className="flex items-center gap-1.5 text-xs font-medium text-slate-600 dark:text-slate-300"
            >
              <FlaskConical className="h-3.5 w-3.5 text-teal-500" />
              Try an example value
            </label>
            <Input
              id="resolved-type-example"
              value={example}
              onChange={(e) => setExample(e.target.value)}
              placeholder={summary.format ? `e.g. a valid ${summary.format}` : `Enter a ${summary.type} value`}
              className="mt-1.5 font-mono text-sm"
              aria-invalid={validation ? !validation.valid : undefined}
            />
            {validation && validation.valid && (
              <p className="mt-1.5 flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Valid against the resolved type.
              </p>
            )}
            {validation && !validation.valid && (
              <div className="mt-1.5 space-y-0.5">
                {(validation.errors ?? [{ message: 'Invalid value' }]).map((err, i) => (
                  <p
                    key={i}
                    className="flex items-center gap-1.5 text-xs text-red-600 dark:text-red-400"
                  >
                    <XCircle className="h-3.5 w-3.5 shrink-0" />
                    {err.path ? `${err.path} ` : ''}
                    {err.message}
                  </p>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default ResolvedTypePreview;

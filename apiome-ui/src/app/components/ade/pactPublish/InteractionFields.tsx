'use client';

/**
 * The rows of the **Write interactions** editor (PFX-8.5, #7302): name / value rows (headers,
 * query, message metadata), provider states with their parameters and suggestions, a body, and the
 * body fields with their matcher chips. Each control has its own label, naming the row it is in.
 */

import * as React from 'react';
import { Plus, X } from 'lucide-react';
import { Button, Input, Label, Textarea } from '@/app/components/ui';
import {
  MATCHERS,
  MATCHER_ARGUMENT,
  matcherLabel,
  placeField,
  type BodyDraft,
  type KeyValue,
  type MatcherDraft,
  type MatcherKind,
  type StateDraft,
} from '@lib/pact-interaction-editor';
import type { StateSuggestion } from '@lib/pact-provider-spec';

/** Props for {@link KeyValueRows}. */
export interface KeyValueRowsProps {
  /** Unique prefix for the controls' ids. */
  idPrefix: string;
  /** What one row is, e.g. `Header`. */
  noun: string;
  rows: KeyValue[];
  onChange: (rows: KeyValue[]) => void;
}

/**
 * Name / value rows with **+ <noun>**.
 *
 * @param props - See {@link KeyValueRowsProps}.
 * @returns The rows.
 */
export function KeyValueRows({ idPrefix, noun, rows, onChange }: KeyValueRowsProps) {
  const set = (index: number, patch: Partial<KeyValue>) => onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <div className="ppub-kv" data-testid={`${idPrefix}-rows`}>
      {rows.map((row, index) => (
        <div className="ppub-kv__row" key={index}>
          <Input
            className="ppx__mono"
            aria-label={`${noun} ${index + 1} name`}
            value={row.name}
            placeholder="Name"
            onChange={(event) => set(index, { name: event.target.value })}
          />
          <Input
            className="ppx__mono"
            aria-label={`${noun} ${index + 1} value`}
            value={row.value}
            placeholder="Value"
            onChange={(event) => set(index, { value: event.target.value })}
          />
          <Button type="button" variant="ghost" size="sm" aria-label={`Remove ${noun.toLowerCase()} ${index + 1}`} onClick={() => onChange(rows.filter((_, i) => i !== index))}>
            <X aria-hidden />
          </Button>
        </div>
      ))}
      <Button type="button" variant="link" size="sm" className="ppub-editor__add" onClick={() => onChange([...rows, { name: '', value: '' }])}>
        <Plus aria-hidden />
        {noun}
      </Button>
    </div>
  );
}

/** Props for {@link StateRows}. */
export interface StateRowsProps {
  idPrefix: string;
  states: StateDraft[];
  suggestions: StateSuggestion[];
  onChange: (states: StateDraft[]) => void;
}

/**
 * The interaction's provider states: a name (suggested from the catalogue and the mock's
 * scenarios) and its parameters, `id = 42`.
 *
 * @param props - See {@link StateRowsProps}.
 * @returns The rows.
 */
export function StateRows({ idPrefix, states, suggestions, onChange }: StateRowsProps) {
  const listId = `${idPrefix}-state-suggestions`;
  const set = (index: number, patch: Partial<StateDraft>) => onChange(states.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  /** A catalogue state's parameters fill an empty parameter box: `id = , kind = `. */
  const pick = (index: number, name: string) => {
    const known = suggestions.find((s) => s.name === name);
    const params = states[index].params;
    set(index, { name, ...(known?.parameters.length && !params.trim() ? { params: known.parameters.map((p) => `${p.name} = `).join(', ') } : {}) });
  };
  return (
    <div className="ppub-kv" data-testid={`${idPrefix}-states`}>
      <datalist id={listId}>
        {suggestions.map((s) => (
          <option key={`${s.source}:${s.name}`} value={s.name}>
            {s.source === 'mock' ? 'Mock scenario' : 'Provider state'}
          </option>
        ))}
      </datalist>
      {states.map((state, index) => {
        const known = suggestions.find((s) => s.name === state.name.trim());
        return (
          <div className="ppub-kv__group" key={index}>
            <div className="ppub-kv__row">
              <Input
                aria-label={`Provider state ${index + 1}`}
                list={listId}
                value={state.name}
                placeholder="an invoice exists"
                onChange={(event) => pick(index, event.target.value)}
              />
              <Input
                className="ppx__mono"
                aria-label={`Parameters of provider state ${index + 1}`}
                value={state.params}
                placeholder="id = 42"
                onChange={(event) => set(index, { params: event.target.value })}
              />
              <Button type="button" variant="ghost" size="sm" aria-label={`Remove provider state ${index + 1}`} onClick={() => onChange(states.filter((_, i) => i !== index))}>
                <X aria-hidden />
              </Button>
            </div>
            {known ? (
              <p className="ppub-hint" data-testid="ppub-state-known">
                {known.source === 'mock'
                  ? `A scenario of the provider’s mock${known.description ? `: ${known.description}` : ''}.`
                  : `In the provider’s state catalogue${known.parameters.length ? ` — takes ${known.parameters.map((p) => `${p.name}${p.required ? ' (required)' : ''}`).join(', ')}` : ''}.`}
              </p>
            ) : null}
          </div>
        );
      })}
      <Button type="button" variant="link" size="sm" className="ppub-editor__add" onClick={() => onChange([...states, { name: '', params: '' }])}>
        <Plus aria-hidden />
        Provider state
      </Button>
    </div>
  );
}

/** Props for {@link BodyField}. */
export interface BodyFieldProps {
  idPrefix: string;
  /** E.g. `Response body`. */
  label: string;
  body: BodyDraft;
  onChange: (body: BodyDraft) => void;
  rows?: number;
}

/**
 * A body: its content type and text. An empty text is no body.
 *
 * @param props - See {@link BodyFieldProps}.
 * @returns The field.
 */
export function BodyField({ idPrefix, label, body, onChange, rows = 6 }: BodyFieldProps) {
  return (
    <div className="ppub-field">
      <div className="ppub-editor__body-head">
        <Label htmlFor={`${idPrefix}-body`}>{label}</Label>
        <Input
          className="ppx__mono ppub-editor__ctype"
          aria-label={`${label} content type`}
          value={body.contentType}
          onChange={(event) => onChange({ ...body, contentType: event.target.value })}
        />
      </div>
      <Textarea
        id={`${idPrefix}-body`}
        className="ppx__mono ppub-editor__code"
        rows={rows}
        spellCheck={false}
        value={body.text}
        placeholder="No body"
        onChange={(event) => onChange({ ...body, text: event.target.value })}
      />
    </div>
  );
}

/** Props for {@link MatcherRows}. */
export interface MatcherRowsProps {
  idPrefix: string;
  /** E.g. `response`, for the labels. */
  side: string;
  matchers: MatcherDraft[];
  /** The new matchers — and, when **+ Field the consumer needs** put a value in it, the new body. */
  onChange: (matchers: MatcherDraft[], body?: BodyDraft) => void;
  /** The body the fields are in, for **+ Field the consumer needs**; without it no value is placed. */
  body?: BodyDraft;
}

/**
 * The body fields the consumer relies on, each with its matcher chip, and **+ Field the consumer
 * needs** (a path, an example value and a matcher; the value is put in the body).
 *
 * @param props - See {@link MatcherRowsProps}.
 * @returns The rows.
 */
export function MatcherRows({ idPrefix, side, matchers, onChange, body }: MatcherRowsProps) {
  const [adding, setAdding] = React.useState<{ path: string; value: string; match: MatcherKind } | null>(null);
  const [problem, setProblem] = React.useState<string | null>(null);
  const set = (index: number, patch: Partial<MatcherDraft>) => onChange(matchers.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  const add = () => {
    if (!adding) return;
    const path = adding.path.trim();
    let value: unknown = adding.value;
    try {
      value = JSON.parse(adding.value);
    } catch {
      // Not JSON: the example is text.
    }
    let nextBody: BodyDraft | undefined;
    if (body && adding.value.trim()) {
      const placed = placeField(body.text, path, value);
      if ('error' in placed) return setProblem(placed.error);
      nextBody = { ...body, text: placed.text };
    }
    // One change for both, so neither overwrites the other.
    onChange([...matchers, { path, match: adding.match, argument: adding.match === 'minType' ? '1' : '' }], nextBody);
    setAdding(null);
    setProblem(null);
  };

  return (
    <div className="ppub-kv" data-testid={`${idPrefix}-matchers`}>
      {matchers.length ? (
        <ul className="ppub-matchers" aria-label={`Fields of the ${side} and their matchers`}>
          {matchers.map((matcher, index) => (
            <li className="ppub-matchers__row" key={index}>
              <Input
                className="ppx__mono"
                aria-label={`Field ${index + 1} of the ${side}`}
                value={matcher.path}
                onChange={(event) => set(index, { path: event.target.value })}
              />
              <select
                className="ppub-select ppub-matcher"
                aria-label={`Matcher of field ${index + 1} of the ${side}`}
                value={matcher.match}
                title={matcherLabel(matcher)}
                onChange={(event) => set(index, { match: event.target.value as MatcherKind })}
              >
                {MATCHERS.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind === 'minType' ? 'min items' : kind === 'maxType' ? 'max items' : kind}
                  </option>
                ))}
              </select>
              {MATCHER_ARGUMENT[matcher.match] ? (
                <Input
                  className="ppx__mono"
                  aria-label={`${MATCHER_ARGUMENT[matcher.match]} for field ${index + 1} of the ${side}`}
                  value={matcher.argument}
                  placeholder={MATCHER_ARGUMENT[matcher.match]}
                  onChange={(event) => set(index, { argument: event.target.value })}
                />
              ) : (
                <span className="ppub-matchers__none" aria-hidden />
              )}
              <Button type="button" variant="ghost" size="sm" aria-label={`Remove field ${index + 1} of the ${side}`} onClick={() => onChange(matchers.filter((_, i) => i !== index))}>
                <X aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {adding ? (
        <div className="ppub-matchers__add" role="group" aria-label={`A field the consumer needs in the ${side}`}>
          <Input
            className="ppx__mono"
            aria-label="Field path"
            value={adding.path}
            placeholder="$.currency"
            onChange={(event) => setAdding({ ...adding, path: event.target.value })}
          />
          <Input
            className="ppx__mono"
            aria-label="Example value"
            value={adding.value}
            placeholder='"EUR"'
            onChange={(event) => setAdding({ ...adding, value: event.target.value })}
          />
          <select
            className="ppub-select ppub-matcher"
            aria-label="Matcher"
            value={adding.match}
            onChange={(event) => setAdding({ ...adding, match: event.target.value as MatcherKind })}
          >
            {MATCHERS.map((kind) => (
              <option key={kind} value={kind}>
                {kind === 'minType' ? 'min items' : kind === 'maxType' ? 'max items' : kind}
              </option>
            ))}
          </select>
          <Button type="button" size="sm" onClick={add}>
            Add field
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setAdding(null)}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button type="button" variant="link" size="sm" className="ppub-editor__add" onClick={() => setAdding({ path: '$.', value: '', match: 'type' })}>
          <Plus aria-hidden />
          Field the consumer needs
        </Button>
      )}
      {problem ? (
        <p className="ppub-hint ppub-hint--danger" role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  );
}

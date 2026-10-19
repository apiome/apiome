/**
 * Consumer bindings and declared-versus-observed — RDG-1.8 (#5765).
 *
 * What the bindings drawer means, kept out of the component so it can be tested without a DOM.
 *
 * A **binding** tells the usage index how to recognise a consumer in traffic: a header, an API key
 * or a JWT claim (whose value the server hashes on create and never shows again), or a user-agent
 * glob. The **runtime report** compares what the consumer declared (its contract) with what its
 * bindings show it calls.
 */

import type { ConsumerContract, RuntimeSummary, SelectionPayloadOperation } from './consumersModel';

/** How a consumer is recognised in traffic. */
export type BindingKind = 'header' | 'api_key' | 'jwt_claim' | 'user_agent';

/** Every kind, in the order the form offers them. */
export const BINDING_KINDS: readonly BindingKind[] = ['header', 'api_key', 'jwt_claim', 'user_agent'];

/** How a kind reads. */
export const BINDING_KIND_LABEL: Readonly<Record<BindingKind, string>> = {
  header: 'Header',
  api_key: 'API key',
  jwt_claim: 'JWT claim',
  user_agent: 'User agent',
};

/** What the name field is called for each kind. */
export const BINDING_NAME_LABEL: Readonly<Record<BindingKind, string>> = {
  header: 'Header name',
  api_key: 'Header carrying the key',
  jwt_claim: 'Claim name',
  user_agent: 'User-agent pattern',
};

/** An example for each kind's name field. */
export const BINDING_NAME_PLACEHOLDER: Readonly<Record<BindingKind, string>> = {
  header: 'x-client-id',
  api_key: 'x-api-key',
  jwt_claim: 'azp',
  user_agent: 'billing-service/*',
};

/** A stored binding as REST returns it — never with its value or its hash. */
export interface ConsumerBinding {
  id: string;
  consumer_id: string;
  kind: BindingKind;
  name: string;
  /** True when a value is bound (every kind but `user_agent`). */
  hashed: boolean;
  key_version: number | null;
  last_matched_at: string | null;
  created_at: string | null;
  deleted_at: string | null;
}

/** One operation on one side of the comparison. */
export interface RuntimeOperation {
  operation_key: string;
  method: string;
  path: string;
  calls: number;
  errors: number;
  last_seen_day: string | null;
}

/** Declared versus observed for one consumer. */
export interface ConsumerRuntime {
  consumer_id: string | null;
  slug: string;
  name: string;
  /** `declared`, `undeclared`, or `none` (the anonymous consumer). */
  contract_state: string;
  since_day: string;
  until_day: string;
  summary: RuntimeSummary;
  declared_and_used: RuntimeOperation[];
  declared_unused: RuntimeOperation[];
  used_undeclared: RuntimeOperation[];
}

/** The body the create form submits. */
export interface BindingDraft {
  kind: BindingKind;
  name: string;
  value: string;
}

/** A fresh form. */
export const EMPTY_BINDING_DRAFT: BindingDraft = { kind: 'header', name: '', value: '' };

/**
 * Whether a kind takes a value (every kind but the user-agent glob).
 *
 * @param kind The binding kind.
 * @returns `true` when the form must ask for the value.
 */
export function bindingNeedsValue(kind: BindingKind): boolean {
  return kind !== 'user_agent';
}

/**
 * Why a draft cannot be submitted yet.
 *
 * @param draft The form's state.
 * @returns The sentence to show, or `null` when the draft can be sent.
 */
export function bindingDraftProblem(draft: BindingDraft): string | null {
  if (!draft.name.trim()) return `Enter the ${BINDING_NAME_LABEL[draft.kind].toLowerCase()}.`;
  if (bindingNeedsValue(draft.kind) && !draft.value) return 'Enter the value to recognise.';
  return null;
}

/**
 * The request body for a draft. A user-agent binding sends no value at all.
 *
 * @param draft The form's state.
 * @returns The body to POST.
 */
export function bindingPayload(draft: BindingDraft): { kind: BindingKind; name: string; value?: string } {
  const name = draft.name.trim();
  return bindingNeedsValue(draft.kind) ? { kind: draft.kind, name, value: draft.value } : { kind: draft.kind, name };
}

/**
 * The line under a binding's name.
 *
 * @param binding The binding.
 * @returns `"Value hashed · last matched 2026-10-17"`, or `"Never matched"` parts.
 */
export function bindingMetaLine(binding: ConsumerBinding): string {
  const value = binding.hashed ? 'Value hashed' : 'Pattern';
  const matched = binding.last_matched_at
    ? `last matched ${binding.last_matched_at.slice(0, 10)}`
    : 'never matched';
  return `${value} · ${matched}`;
}

/**
 * How many calls, in words.
 *
 * @param calls The count.
 * @returns `"1 call"` or `"1,025 calls"`.
 */
export function callsLabel(calls: number): string {
  return calls === 1 ? '1 call' : `${calls.toLocaleString('en-US')} calls`;
}

/**
 * The one-line summary of a runtime report.
 *
 * @param summary The counts.
 * @returns `"1,025 calls · 2 declared and used · 1 declared, unused · 1 used, undeclared"`.
 */
export function runtimeSummaryLine(summary: RuntimeSummary): string {
  if (summary.calls === 0 && summary.declared_unused === 0) return 'No attributed traffic in this window.';
  return [
    callsLabel(summary.calls),
    `${summary.declared_and_used} declared and used`,
    `${summary.declared_unused} declared, unused`,
    `${summary.used_undeclared} used, undeclared`,
  ].join(' · ');
}

/**
 * The selection that adds one observed operation to a consumer's current contract.
 *
 * "Add to contract" is not a new writer: it re-submits everything already declared — every
 * operation with its fields — plus the new operation as a whole-operation declaration, through
 * the same `PUT …/contract` the picker uses. The server writes the next revision.
 *
 * @param contract The consumer's current contract, or `null` when it has declared nothing.
 * @param operation The observed operation to add.
 * @returns The operations to submit, ordered by path then method; the existing declaration is
 *   returned unchanged when it already contains the operation.
 */
export function contractWithOperation(
  contract: ConsumerContract | null,
  operation: { method: string; path: string },
): SelectionPayloadOperation[] {
  const declared: SelectionPayloadOperation[] = (contract?.surface.operations ?? []).map((op) => ({
    method: op.method,
    path: op.path,
    fields: op.fields.map((field) => ({
      location: field.location,
      path: field.path,
      ...(field.status ? { status: field.status } : {}),
      ...(field.media_type ? { media_type: field.media_type } : {}),
    })),
  }));
  const method = operation.method.toLowerCase();
  if (!declared.some((op) => op.method.toLowerCase() === method && op.path === operation.path)) {
    declared.push({ method, path: operation.path, fields: [] });
  }
  return declared.sort((a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method));
}

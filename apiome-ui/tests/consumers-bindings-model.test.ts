/**
 * The bindings drawer's derivations — RDG-1.8 (#5765).
 *
 * The rule that matters most is "Add to contract": it must re-submit everything already declared,
 * fields and all, plus the observed operation, so writing the next revision never silently drops
 * part of the existing contract.
 */

import {
  EMPTY_BINDING_DRAFT,
  bindingDraftProblem,
  bindingMetaLine,
  bindingNeedsValue,
  bindingPayload,
  callsLabel,
  contractWithOperation,
  runtimeSummaryLine,
  type ConsumerBinding,
} from '../src/app/components/ade/consumers/bindingsModel';
import type { ConsumerContract } from '../src/app/components/ade/consumers/consumersModel';

const CONTRACT = {
  surface: {
    schema_version: 'apiome.consumer.contract/v1',
    operations: [
      {
        method: 'get',
        path: '/pets',
        pointer: '/paths/~1pets/get',
        operation_id: null,
        summary: null,
        fields: [
          {
            pointer: '/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total',
            schema_pointer: '/components/schemas/PetList/properties/total',
            location: 'response',
            status: '200',
            media_type: 'application/json',
            path: 'total',
          },
          {
            pointer: '/paths/~1pets/get/parameters/query:limit',
            schema_pointer: '/paths/~1pets/get/parameters/query:limit',
            location: 'parameter',
            status: null,
            media_type: null,
            path: 'limit',
          },
        ],
      },
    ],
  },
} as unknown as ConsumerContract;

describe('contractWithOperation', () => {
  it('keeps every declared operation and field and adds the observed one', () => {
    expect(contractWithOperation(CONTRACT, { method: 'GET', path: '/users/{userId}/orders' })).toEqual([
      {
        method: 'get',
        path: '/pets',
        fields: [
          { location: 'response', path: 'total', status: '200', media_type: 'application/json' },
          { location: 'parameter', path: 'limit' },
        ],
      },
      { method: 'get', path: '/users/{userId}/orders', fields: [] },
    ]);
  });

  it('starts a contract for a consumer that has declared nothing', () => {
    expect(contractWithOperation(null, { method: 'post', path: '/pets' })).toEqual([
      { method: 'post', path: '/pets', fields: [] },
    ]);
  });

  it('does not duplicate an operation that is already declared', () => {
    const payload = contractWithOperation(CONTRACT, { method: 'GET', path: '/pets' });
    expect(payload).toHaveLength(1);
    expect(payload[0].fields).toHaveLength(2);
  });

  it('orders by path then method', () => {
    const payload = contractWithOperation(CONTRACT, { method: 'delete', path: '/pets' });
    expect(payload.map((op) => `${op.method} ${op.path}`)).toEqual(['delete /pets', 'get /pets']);
  });
});

describe('the binding form', () => {
  it('asks for a value for every kind but the user agent', () => {
    expect(bindingNeedsValue('header')).toBe(true);
    expect(bindingNeedsValue('api_key')).toBe(true);
    expect(bindingNeedsValue('jwt_claim')).toBe(true);
    expect(bindingNeedsValue('user_agent')).toBe(false);
  });

  it('names what is missing', () => {
    expect(bindingDraftProblem(EMPTY_BINDING_DRAFT)).toBe('Enter the header name.');
    expect(bindingDraftProblem({ kind: 'header', name: 'x-client-id', value: '' })).toBe(
      'Enter the value to recognise.',
    );
    expect(bindingDraftProblem({ kind: 'user_agent', name: 'billing/*', value: '' })).toBeNull();
  });

  it('never sends a value for a user-agent pattern', () => {
    expect(bindingPayload({ kind: 'user_agent', name: ' billing/* ', value: 'leftover' })).toEqual({
      kind: 'user_agent',
      name: 'billing/*',
    });
    expect(bindingPayload({ kind: 'api_key', name: 'x-api-key', value: ' k ' })).toEqual({
      kind: 'api_key',
      name: 'x-api-key',
      value: ' k ',
    });
  });
});

describe('the lines the drawer reads', () => {
  const binding: ConsumerBinding = {
    id: 'b1',
    consumer_id: 'c1',
    kind: 'header',
    name: 'x-client-id',
    hashed: true,
    key_version: 1,
    last_matched_at: '2026-10-17T09:30:00Z',
    created_at: null,
    deleted_at: null,
  };

  it('describes a binding without its value', () => {
    expect(bindingMetaLine(binding)).toBe('Value hashed · last matched 2026-10-17');
    expect(bindingMetaLine({ ...binding, kind: 'user_agent', hashed: false, last_matched_at: null })).toBe(
      'Pattern · never matched',
    );
  });

  it('counts calls', () => {
    expect(callsLabel(1)).toBe('1 call');
    expect(callsLabel(1025)).toBe('1,025 calls');
  });

  it('summarises a report', () => {
    expect(
      runtimeSummaryLine({ calls: 1025, declared_and_used: 2, declared_unused: 1, used_undeclared: 1, last_seen_day: null }),
    ).toBe('1,025 calls · 2 declared and used · 1 declared, unused · 1 used, undeclared');
    expect(
      runtimeSummaryLine({ calls: 0, declared_and_used: 0, declared_unused: 0, used_undeclared: 0, last_seen_day: null }),
    ).toBe('No attributed traffic in this window.');
  });
});

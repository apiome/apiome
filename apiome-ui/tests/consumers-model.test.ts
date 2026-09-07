/**
 * The consumer registry's rules — CTG-4.1 (#4479).
 *
 * `consumersModel` is where every judgement the Consumers screen makes lives, so this is
 * where they are pinned: what a row's contract status is, how a surface reads in one line,
 * and — the part with real consequences — what the picker's checkbox state turns into when it
 * is submitted. A payload that named a pointer, or that dropped an operation whose fields were
 * all unticked, would store a contract that says something the person did not.
 */

import {
  CONSUMER_FACETS,
  CONSUMER_STATUS_LABEL,
  buildSelectionPayload,
  consumerFacetCounts,
  consumerStatus,
  contractProvenanceLine,
  contractSummaryLine,
  fieldKey,
  groupAvailableFields,
  groupUnresolved,
  isFieldPicked,
  isOperationPicked,
  matchesConsumerFacet,
  operationKey,
  operationLabel,
  searchConsumers,
  selectionFromContract,
  selectionTotals,
  sortConsumers,
  toggleField,
  toggleOperation,
  unresolvedReasonLabel,
  type AvailableOperation,
  type ConsumerContract,
  type ConsumerSummary,
  type UnresolvedInteraction,
} from '@/app/components/ade/consumers/consumersModel';

// ---------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------

function consumer(overrides: Partial<ConsumerSummary['consumer']> = {}) {
  return {
    id: 'c1',
    tenant_id: 't1',
    project_id: 'p1',
    slug: 'billing-service',
    name: 'Billing Service',
    description: null,
    owner: 'Payments squad',
    contact: null,
    metadata: {},
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    deleted_at: null,
    ...overrides,
  };
}

function contract(overrides: Partial<ConsumerContract> = {}): ConsumerContract {
  return {
    id: 'k1',
    consumer_id: 'c1',
    revision: 2,
    is_current: true,
    source: 'manual',
    version_id: 'v1',
    version_label: '1.2.0',
    surface: {
      schema_version: 'apiome.consumer.contract/v1',
      operations: [
        {
          method: 'get',
          path: '/pets',
          pointer: '/paths/~1pets/get',
          operation_id: 'listPets',
          summary: 'List pets',
          fields: [
            {
              pointer: '/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total',
              schema_pointer: '/components/schemas/PetList/properties/total',
              location: 'response',
              status: '200',
              media_type: 'application/json',
              path: 'total',
            },
          ],
        },
      ],
    },
    operation_count: 1,
    field_count: 1,
    unresolved: [],
    unresolved_count: 0,
    source_metadata: {},
    source_digest: null,
    note: null,
    actor_label: null,
    created_at: '2026-09-02T00:00:00Z',
    ...overrides,
  };
}

function summary(overrides: Partial<ConsumerSummary> = {}): ConsumerSummary {
  return { consumer: consumer(), contract: contract(), ...overrides };
}

const CATALOGUE: AvailableOperation[] = [
  {
    method: 'get',
    path: '/pets',
    pointer: '/paths/~1pets/get',
    operation_id: 'listPets',
    summary: 'List pets',
    tags: ['pets'],
    truncated: false,
    fields: [
      {
        pointer: '/paths/~1pets/get/parameters/query:limit',
        schema_pointer: '/paths/~1pets/get/parameters/query:limit',
        location: 'parameter',
        path: 'limit',
        status: null,
        media_type: null,
        type_name: 'integer',
        required: false,
      },
      {
        pointer: '/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total',
        schema_pointer: '/components/schemas/PetList/properties/total',
        location: 'response',
        path: 'total',
        status: '200',
        media_type: 'application/json',
        type_name: 'integer',
        required: false,
      },
    ],
  },
  {
    method: 'post',
    path: '/pets',
    pointer: '/paths/~1pets/post',
    operation_id: 'createPet',
    summary: null,
    tags: [],
    truncated: false,
    fields: [
      {
        pointer: '/paths/~1pets/post/requestBody/content/application~1json/schema/properties/name',
        schema_pointer: '/components/schemas/Pet/properties/name',
        location: 'request',
        path: 'name',
        status: null,
        media_type: 'application/json',
        type_name: 'string',
        required: true,
      },
    ],
  },
];

// ---------------------------------------------------------------------------------------
// Status
// ---------------------------------------------------------------------------------------

describe('consumerStatus', () => {
  it('is "none" for a consumer that has declared nothing', () => {
    expect(consumerStatus(summary({ contract: null }))).toBe('none');
  });

  it('is "declared" when the contract resolved cleanly', () => {
    expect(consumerStatus(summary())).toBe('declared');
  });

  it('is "partial" when interactions could not be resolved', () => {
    expect(
      consumerStatus(
        summary({
          contract: contract({
            unresolved_count: 3,
            unresolved: [
              { reason: 'operation-not-found', message: 'gone', description: null, method: null, path: null, status: null, field_path: null },
            ],
          }),
        }),
      ),
    ).toBe('partial');
  });

  it('is "partial" when a stored revision declares no operations at all', () => {
    // A Pact import that resolved nothing is a fact about the API, not a clean contract.
    expect(consumerStatus(summary({ contract: contract({ operation_count: 0 }) }))).toBe(
      'partial',
    );
  });

  it('names every status', () => {
    expect(Object.keys(CONSUMER_STATUS_LABEL).sort()).toEqual([
      'declared',
      'none',
      'partial',
    ]);
  });
});

// ---------------------------------------------------------------------------------------
// Summaries
// ---------------------------------------------------------------------------------------

describe('contractSummaryLine', () => {
  it('says a consumer has declared nothing rather than showing zeros', () => {
    expect(contractSummaryLine(null)).toBe('Nothing declared yet');
  });

  it('counts operations and fields', () => {
    expect(contractSummaryLine(contract({ operation_count: 4, field_count: 12 }))).toBe(
      '4 operations · 12 fields',
    );
  });

  it('singularises a count of one', () => {
    expect(contractSummaryLine(contract({ operation_count: 1, field_count: 1 }))).toBe(
      '1 operation · 1 field',
    );
  });

  it('never hides an unresolved tally', () => {
    expect(
      contractSummaryLine(contract({ operation_count: 4, field_count: 9, unresolved_count: 3 })),
    ).toBe('4 operations · 9 fields · 3 unresolved');
  });
});

describe('contractProvenanceLine', () => {
  it('says which revision, how it arrived, and against what', () => {
    expect(contractProvenanceLine(contract({ source: 'pact' }))).toBe(
      'Revision 2 · imported from Pact · against 1.2.0',
    );
  });

  it('is empty when nothing is declared', () => {
    expect(contractProvenanceLine(null)).toBe('');
  });
});

describe('unresolved reasons', () => {
  it('names every reason the server can send', () => {
    for (const reason of [
      'operation-not-found',
      'method-not-declared',
      'status-not-declared',
      'media-type-not-declared',
      'field-not-found',
      'parameter-not-declared',
      'interaction-not-http',
      'interaction-malformed',
    ]) {
      expect(unresolvedReasonLabel(reason)).not.toBe('');
      expect(unresolvedReasonLabel(reason)).not.toBe(reason);
    }
  });

  it('falls back to the code for a reason this build does not know', () => {
    // A new server-side reason must stay readable rather than rendering as blank.
    expect(unresolvedReasonLabel('something-new')).toBe('something-new');
  });

  it('groups entries by reason, most numerous first', () => {
    const entries: UnresolvedInteraction[] = [
      { reason: 'field-not-found', message: 'a', description: null, method: null, path: null, status: null, field_path: null },
      { reason: 'operation-not-found', message: 'b', description: null, method: null, path: null, status: null, field_path: null },
      { reason: 'field-not-found', message: 'c', description: null, method: null, path: null, status: null, field_path: null },
    ];
    const groups = groupUnresolved(entries);
    expect(groups.map((group) => [group.reason, group.entries.length])).toEqual([
      ['field-not-found', 2],
      ['operation-not-found', 1],
    ]);
    expect(groups[0].label).toBe('Field not in the schema');
  });
});

// ---------------------------------------------------------------------------------------
// Search, facets, sort
// ---------------------------------------------------------------------------------------

describe('searchConsumers', () => {
  const rows = [
    summary(),
    summary({ consumer: consumer({ id: 'c2', slug: 'checkout', name: 'Checkout', owner: null }), contract: null }),
  ];

  it('returns everything for an empty query', () => {
    expect(searchConsumers(rows, '   ')).toHaveLength(2);
  });

  it('matches the handle and the display name', () => {
    expect(searchConsumers(rows, 'checkout').map((row) => row.consumer.slug)).toEqual([
      'checkout',
    ]);
  });

  it('matches a declared path, which is the question the screen exists for', () => {
    expect(searchConsumers(rows, '/pets').map((row) => row.consumer.slug)).toEqual([
      'billing-service',
    ]);
  });
});

describe('facets', () => {
  const rows = [
    summary(),
    summary({ consumer: consumer({ id: 'c2', slug: 'checkout' }), contract: null }),
    summary({ consumer: consumer({ id: 'c3', slug: 'ledger' }), contract: contract({ unresolved_count: 1 }) }),
  ];

  it('counts each chip, with "all" covering everything', () => {
    expect(consumerFacetCounts(rows)).toEqual({ all: 3, declared: 1, partial: 1, none: 1 });
  });

  it('matches a row against its own status', () => {
    expect(matchesConsumerFacet(rows[1], 'none')).toBe(true);
    expect(matchesConsumerFacet(rows[1], 'declared')).toBe(false);
    expect(matchesConsumerFacet(rows[1], 'all')).toBe(true);
  });

  it('offers "all" plus one chip per status', () => {
    expect([...CONSUMER_FACETS]).toEqual(['all', 'declared', 'partial', 'none']);
  });
});

describe('sortConsumers', () => {
  const rows = [
    summary({ consumer: consumer({ id: 'c1', name: 'Zeta', owner: 'A team' }) }),
    summary({
      consumer: consumer({ id: 'c2', name: 'Alpha', owner: 'B team' }),
      contract: contract({ operation_count: 9 }),
    }),
  ];

  it('sorts by name', () => {
    expect(sortConsumers(rows, 'consumer', 'asc').map((row) => row.consumer.name)).toEqual([
      'Alpha',
      'Zeta',
    ]);
  });

  it('sorts by declared surface size, numerically', () => {
    expect(sortConsumers(rows, 'surface', 'desc').map((row) => row.consumer.name)).toEqual([
      'Alpha',
      'Zeta',
    ]);
  });

  it('sorts a consumer with no contract below every consumer with one', () => {
    const withNone = [...rows, summary({ consumer: consumer({ id: 'c3', name: 'Nil' }), contract: null })];
    expect(sortConsumers(withNone, 'surface', 'asc')[0].consumer.name).toBe('Nil');
  });

  it('never mutates its input', () => {
    const original = [...rows];
    sortConsumers(rows, 'consumer', 'desc');
    expect(rows).toEqual(original);
  });
});

// ---------------------------------------------------------------------------------------
// The picker
// ---------------------------------------------------------------------------------------

describe('picker keys', () => {
  it('keys an operation by method and path', () => {
    expect(operationKey({ method: 'GET', path: '/pets' })).toBe('get /pets');
    expect(operationLabel({ method: 'get', path: '/pets' })).toBe('GET /pets');
  });

  it('keys a field by location, status and path, because a status changes the meaning', () => {
    expect(fieldKey({ location: 'response', status: '200', path: 'id' })).not.toBe(
      fieldKey({ location: 'response', status: '400', path: 'id' }),
    );
  });
});

describe('selectionFromContract', () => {
  it('starts an edit from what is already declared', () => {
    const selection = selectionFromContract(contract());
    expect(isOperationPicked(selection, { method: 'get', path: '/pets' })).toBe(true);
    expect(
      isFieldPicked(selection, { method: 'get', path: '/pets' }, {
        location: 'response',
        status: '200',
        path: 'total',
      }),
    ).toBe(true);
  });

  it('is empty when nothing is declared', () => {
    expect(selectionFromContract(null)).toEqual({});
  });
});

describe('toggling', () => {
  it('unpicking an operation takes its fields with it', () => {
    const picked = selectionFromContract(contract());
    const cleared = toggleOperation(picked, { method: 'get', path: '/pets' });
    expect(cleared).toEqual({});
  });

  it('picking a field picks its operation too', () => {
    const selection = toggleField({}, { method: 'get', path: '/pets' }, {
      location: 'response',
      status: '200',
      path: 'total',
    });
    expect(isOperationPicked(selection, { method: 'get', path: '/pets' })).toBe(true);
    expect(selectionTotals(selection)).toEqual({ operations: 1, fields: 1 });
  });

  it('unpicking a field leaves its operation declared', () => {
    let selection = toggleField({}, { method: 'get', path: '/pets' }, {
      location: 'response',
      status: '200',
      path: 'total',
    });
    selection = toggleField(selection, { method: 'get', path: '/pets' }, {
      location: 'response',
      status: '200',
      path: 'total',
    });
    expect(isOperationPicked(selection, { method: 'get', path: '/pets' })).toBe(true);
    expect(selectionTotals(selection)).toEqual({ operations: 1, fields: 0 });
  });
});

describe('buildSelectionPayload', () => {
  it('names operations and fields, never pointers', () => {
    const selection = toggleField({}, CATALOGUE[0], CATALOGUE[0].fields[1]);
    const payload = buildSelectionPayload(selection, CATALOGUE);
    expect(payload).toEqual([
      {
        method: 'get',
        path: '/pets',
        fields: [{ location: 'response', path: 'total', status: '200' }],
      },
    ]);
    expect(JSON.stringify(payload)).not.toContain('pointer');
  });

  it('keeps an operation whose fields are all unticked', () => {
    // "I call this and I do not care which fields come back" is a real contract.
    const payload = buildSelectionPayload(toggleOperation({}, CATALOGUE[1]), CATALOGUE);
    expect(payload).toEqual([{ method: 'post', path: '/pets', fields: [] }]);
  });

  it('omits a status for a field that has none', () => {
    const selection = toggleField({}, CATALOGUE[1], CATALOGUE[1].fields[0]);
    expect(buildSelectionPayload(selection, CATALOGUE)[0].fields[0]).toEqual({
      location: 'request',
      path: 'name',
    });
  });

  it('orders by path then method, so the same picks always produce the same request', () => {
    const selection = { 'post /pets': [], 'get /pets': [] };
    expect(buildSelectionPayload(selection, CATALOGUE).map((op) => op.method)).toEqual([
      'get',
      'post',
    ]);
  });

  it('drops a pick whose operation is not in the catalogue', () => {
    // The catalogue is the specification; a pick that does not appear in it cannot be honoured.
    expect(buildSelectionPayload({ 'get /ghost': [] }, CATALOGUE)).toEqual([]);
  });
});

describe('groupAvailableFields', () => {
  it('reads in exchange order and omits empty groups', () => {
    expect(groupAvailableFields(CATALOGUE[0]).map((group) => group.location)).toEqual([
      'parameter',
      'response',
    ]);
    expect(groupAvailableFields(CATALOGUE[1]).map((group) => group.label)).toEqual([
      'Request body',
    ]);
  });
});

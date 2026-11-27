/**
 * The **Write interactions** editor's model — PFX-8.5 (#7302):
 *
 * * a pact written in the editor round-trips through the pact reader without loss, for HTTP,
 *   message, GraphQL and gRPC interactions, and the page's own reader (`readPactFile`) accepts it
 *   with the right kinds;
 * * every problem that stops a pact is named; nothing builds while one remains;
 * * a path that is not in the spec is flagged, never blocked;
 * * Fill from the spec fills the status, the example and a matcher per field;
 * * what a foreign pact carries that the editor cannot hold is reported with the reason.
 */

import {
  buildPact,
  draftIsReady,
  draftProblems,
  fillFromSpec,
  formatStateParams,
  listLabel,
  matcherForField,
  matcherProblem,
  newInteraction,
  parseStateParams,
  placeField,
  readPactIntoEditor,
  specFlag,
  type EditorDraft,
  type InteractionDraft,
} from '../lib/pact-interaction-editor';
import { readPactFile } from '../lib/pact-publish-page';
import type { SpecOperation } from '../lib/pact-provider-spec';

let counter = 0;
const nextId = () => `ix${counter++}`;

beforeEach(() => {
  counter = 0;
});

/** An interaction of a kind with fields set. */
function ix(kind: InteractionDraft['kind'], patch: Partial<InteractionDraft>): InteractionDraft {
  return { ...newInteraction(nextId(), kind), ...patch };
}

const json = (value: unknown) => JSON.stringify(value, null, 2);

/** One of each kind, every editable field used. */
function fullDraft(): EditorDraft {
  return {
    consumer: 'Orders UI',
    provider: 'Billing Service',
    interactions: [
      ix('http', {
        description: 'get invoice 42',
        states: [{ name: 'an invoice exists', params: 'id = 42, currency = EUR, code = "42"' }],
        method: 'GET',
        path: '/invoices/42',
        query: [
          { name: 'expand', value: 'lines' },
          { name: 'expand', value: 'payer' },
        ],
        requestHeaders: [{ name: 'Accept', value: 'application/json' }],
        status: '200',
        responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
        responseBody: { text: json({ id: 42, amount: 1200, currency: 'EUR', lines: [{ sku: 'A-1' }] }), contentType: 'application/json' },
        responseMatchers: [
          { path: '$.id', match: 'integer', argument: '' },
          { path: '$.id', match: 'notEmpty', argument: '' },
          { path: '$.currency', match: 'regex', argument: '^[A-Z]{3}$' },
          { path: '$.lines', match: 'minType', argument: '1' },
          { path: '$.lines[*].sku', match: 'type', argument: '' },
        ],
      }),
      ix('http', {
        description: 'create an invoice',
        method: 'POST',
        path: '/invoices',
        requestBody: { text: json({ amount: 5 }), contentType: 'application/json' },
        requestMatchers: [{ path: '$.amount', match: 'number', argument: '' }],
        status: '201',
        responseBody: { text: 'created', contentType: 'text/plain' },
        responseMatchers: [{ path: '$', match: 'include', argument: 'creat' }],
      }),
      ix('message', {
        description: 'an invoice paid event',
        states: [{ name: 'an invoice was paid', params: '' }],
        responseBody: { text: json({ invoiceId: 42, paidAt: '2026-01-31' }), contentType: 'application/json' },
        metadata: [{ name: 'topic', value: 'invoices' }],
        responseMatchers: [{ path: '$.paidAt', match: 'date', argument: 'yyyy-MM-dd' }],
      }),
      ix('graphql', {
        description: 'invoice by graphql',
        path: '/graphql',
        graphqlQuery: 'query Invoice($id: ID!) { invoice(id: $id) { id } }',
        graphqlVariables: json({ id: '42' }),
        operationName: 'Invoice',
        requestHeaders: [{ name: 'Authorization', value: 'Bearer token' }],
        responseBody: { text: json({ data: { invoice: { id: '42' } } }), contentType: 'application/json' },
        responseMatchers: [{ path: '$.data.invoice.id', match: 'type', argument: '' }],
      }),
      ix('grpc', {
        description: 'get invoice over grpc',
        service: 'billing.Invoices/GetInvoice',
        requestBody: { text: json({ id: '42' }), contentType: 'application/json' },
        responseBody: { text: json({ id: '42', amount: 1200 }), contentType: 'application/json' },
        responseMatchers: [{ path: '$.amount', match: 'integer', argument: '' }],
      }),
    ],
  };
}

/** A draft without its editor-only ids. */
const withoutIds = (draft: EditorDraft) => ({ ...draft, interactions: draft.interactions.map((one) => ({ ...one, id: '' })) });

describe('round trip', () => {
  it('a pact written in the editor reads back into the same draft, and builds the same document', () => {
    const draft = fullDraft();
    const built = buildPact(draft);
    if (!('pact' in built)) throw new Error(JSON.stringify(built.problems));
    const text = JSON.stringify(built.pact);
    const read = readPactIntoEditor(text, nextId);
    if ('error' in read) throw new Error(read.error);
    expect(read.unsupported).toEqual([]);
    expect(withoutIds(read.draft)).toEqual(withoutIds(draft));
    const again = buildPact(read.draft);
    expect('pact' in again && again.pact).toEqual(built.pact);
  });

  it('the page’s reader accepts the written pact: Pact v4, five interactions, all four kinds', () => {
    const built = buildPact(fullDraft());
    if (!('pact' in built)) throw new Error('not built');
    const row = readPactFile('w', 'Written', JSON.stringify(built.pact));
    expect(row.problem).toBeNull();
    expect(row).toMatchObject({ consumer: 'Orders UI', provider: 'Billing Service', specVersion: '4.0', interactions: 5 });
    expect(row.kinds.sort()).toEqual(['GraphQL', 'HTTP', 'Message', 'gRPC']);
  });

  it('writes Pact v4 shapes: typed interactions, multi-value headers, combined body rules', () => {
    const built = buildPact(fullDraft());
    if (!('pact' in built)) throw new Error('not built');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the test reads deep into the written document
    const [http, post, message, graphql, grpc] = built.pact.interactions as Array<Record<string, any>>;
    expect(http.type).toBe('Synchronous/HTTP');
    expect(http.providerStates).toEqual([{ name: 'an invoice exists', params: { id: 42, currency: 'EUR', code: '42' } }]);
    expect(http.request.query).toEqual({ expand: ['lines', 'payer'] });
    expect(http.response.body).toEqual({ content: expect.objectContaining({ id: 42 }), contentType: 'application/json', encoded: false });
    expect(http.response.matchingRules.body['$.id']).toEqual({ combine: 'AND', matchers: [{ match: 'integer' }, { match: 'notEmpty' }] });
    expect(http.response.matchingRules.body['$.lines']).toEqual({ combine: 'AND', matchers: [{ match: 'type', min: 1 }] });
    expect(post.response.body).toEqual({ content: 'created', contentType: 'text/plain', encoded: false });
    expect(message.type).toBe('Asynchronous/Messages');
    expect(message.metadata).toEqual({ topic: 'invoices' });
    expect(graphql.request).toMatchObject({ method: 'POST', path: '/graphql', body: { content: { query: expect.any(String), variables: { id: '42' }, operationName: 'Invoice' } } });
    expect(grpc).toMatchObject({ type: 'Synchronous/Messages', transport: 'grpc', pluginConfiguration: { protobuf: { service: 'billing.Invoices/GetInvoice' } } });
    expect(grpc.response).toHaveLength(1);
    expect(built.pact.metadata).toMatchObject({ pactSpecification: { version: '4.0' } });
  });

  it('rules on one path typed apart are written together, and the document survives a second trip', () => {
    const draft: EditorDraft = {
      consumer: 'A',
      provider: 'B',
      interactions: [
        ix('http', {
          description: 'x',
          path: '/x',
          responseMatchers: [
            { path: '$.a', match: 'integer', argument: '' },
            { path: '$.b', match: 'type', argument: '' },
            { path: '$.a', match: 'notEmpty', argument: '' },
          ],
        }),
      ],
    };
    const built = buildPact(draft);
    if (!('pact' in built)) throw new Error('not built');
    const read = readPactIntoEditor(JSON.stringify(built.pact), nextId);
    if ('error' in read) throw new Error(read.error);
    expect(read.draft.interactions[0].responseMatchers.map((m) => `${m.path} ${m.match}`)).toEqual(['$.a integer', '$.a notEmpty', '$.b type']);
    const again = buildPact(read.draft);
    expect('pact' in again && again.pact).toEqual(built.pact);
  });

  it('an empty message or reply round-trips as no contents', () => {
    const draft: EditorDraft = { consumer: 'A', provider: 'B', interactions: [ix('message', { description: 'ping' }), ix('grpc', { description: 'call', service: 'a.B/C' })] };
    const built = buildPact(draft);
    if (!('pact' in built)) throw new Error('not built');
    const read = readPactIntoEditor(JSON.stringify(built.pact), nextId);
    if ('error' in read) throw new Error(read.error);
    expect(withoutIds(read.draft)).toEqual(withoutIds(draft));
  });
});

describe('reading a foreign pact', () => {
  it('reads a Pact v2 HTTP interaction and a v3 message', () => {
    const v2 = JSON.stringify({
      consumer: { name: 'A' },
      provider: { name: 'B' },
      interactions: [{ description: 'x', providerState: 'ready', request: { method: 'get', path: '/x', query: 'a=1&a=2' }, response: { status: 200, body: { ok: true } } }],
      messages: [{ description: 'm', contents: { id: 1 }, metadata: { partition: 3 } }],
    });
    const read = readPactIntoEditor(v2, nextId);
    if ('error' in read) throw new Error(read.error);
    const [http, message] = read.draft.interactions;
    expect(http).toMatchObject({ kind: 'http', method: 'GET', states: [{ name: 'ready', params: '' }], query: [{ name: 'a', value: '1' }, { name: 'a', value: '2' }] });
    expect(JSON.parse(http.responseBody.text)).toEqual({ ok: true });
    expect(message).toMatchObject({ kind: 'message', metadata: [{ name: 'partition', value: '3' }] });
    expect(read.unsupported).toEqual(['Message 1: metadata values that are not text are shown as JSON text and written back as text.']);
  });

  it('reports, with the reason, everything it cannot hold', () => {
    const text = JSON.stringify({
      consumer: { name: 'A' },
      provider: { name: 'B' },
      interactions: [
        {
          type: 'Synchronous/HTTP',
          description: 'x',
          pending: true,
          request: { method: 'GET', path: '/x', matchingRules: { header: { Accept: { matchers: [{ match: 'regex', regex: 'json' }] } } }, generators: { body: {} } },
          response: {
            status: 200,
            matchingRules: {
              body: {
                '$.a': { combine: 'OR', matchers: [{ match: 'integer' }, { match: 'null' }] },
                '$.b': { matchers: [{ match: 'type', min: 1, max: 3 }] },
                '$.c': { matchers: [{ match: 'eachKey', rules: [] }] },
              },
            },
          },
        },
        { type: 'Synchronous/Messages', description: 'kafka reply', request: {}, response: [] },
        { type: 'Some/Plugin', description: 'p' },
        {
          type: 'Synchronous/Messages',
          transport: 'grpc',
          description: 'g',
          pluginConfiguration: { protobuf: { service: 'a.B/C', descriptorKey: 'k' } },
          request: { contents: { content: 'AAEC', encoded: 'base64', contentType: 'application/protobuf' } },
          response: [{ contents: { content: 'AA==' } }, { contents: { content: 'AQ==' } }],
        },
      ],
    });
    const read = readPactIntoEditor(text, nextId);
    if ('error' in read) throw new Error(read.error);
    expect(read.draft.interactions.map((i) => i.kind)).toEqual(['http', 'grpc']);
    expect(read.unsupported).toEqual([
      'Interaction 1 has pending; the editor does not write it, so it was not read.',
      'Interaction 1’s request has header matching rules; the editor holds body rules only, so they were not read.',
      'Interaction 1’s response: the rules on $.a are combined with OR; the editor combines with AND.',
      'Interaction 1’s response: the type rule on $.b sets both min and max; add them as two rules.',
      'Interaction 1’s response: the eachKey rule on $.c is not one the editor writes, so it was not read.',
      'Interaction 1 has generators; the editor does not write them, so they were not read.',
      'Interaction 2 is a synchronous message that is not gRPC; the editor does not write those, so it was not read.',
      'Interaction 3 is a Some/Plugin interaction, which the editor does not write; it was not read.',
      'Interaction 4: the protobuf plugin’s descriptorKey are not kept; the editor writes the service only.',
      'Interaction 4 has 2 replies; the editor holds the first.',
      'Interaction 4’s request: the body is base64 binary content; it is shown as text and written back as text.',
    ]);
  });

  it('a POST to /graphql with other body members stays an HTTP interaction', () => {
    const text = JSON.stringify({
      consumer: { name: 'A' },
      provider: { name: 'B' },
      interactions: [{ type: 'Synchronous/HTTP', description: 'x', request: { method: 'POST', path: '/graphql', body: { content: { query: 'q', extensions: {} }, contentType: 'application/json' } }, response: { status: 200 } }],
    });
    const read = readPactIntoEditor(text, nextId);
    expect('draft' in read && read.draft.interactions[0].kind).toBe('http');
  });

  it.each([
    ['not JSON', 'nope', 'Not a pact: the text is not JSON.'],
    ['an array', '[]', 'Not a pact: the text is not a JSON object.'],
    ['interactions that are not a list', '{"interactions": {}}', 'Not a pact: interactions must be a list.'],
  ])('refuses %s', (_what, text, error) => {
    expect(readPactIntoEditor(text, nextId)).toEqual({ error });
  });
});

describe('problems', () => {
  it('names every problem and builds nothing while one remains', () => {
    const bad = ix('http', { description: '', method: 'GET', path: 'invoices?x=1', status: '42', responseBody: { text: '{', contentType: 'application/json' }, states: [{ name: '', params: 'id' }] });
    const problems = draftProblems({ consumer: '', provider: 'B', interactions: [bad] });
    expect(problems.pair).toEqual(['Name the consumer: the application that makes these calls.']);
    expect(problems.interactions[bad.id]).toEqual([
      'Describe the interaction: “get invoice 42”.',
      'A provider state has no name.',
      'Parameters of “a state”: “id” is not name = value.',
      'The path starts with /.',
      'The response status is a number from 100 to 599.',
      'The response body is not valid JSON.',
    ]);
    expect(draftIsReady(problems)).toBe(false);
    expect('problems' in buildPact({ consumer: '', provider: 'B', interactions: [bad] })).toBe(true);
  });

  it('flags a query string in the path, bad GraphQL variables, a bad gRPC name and duplicates', () => {
    const a = ix('http', { description: 'same', path: '/a?b=1' });
    const b = ix('http', { description: 'same', path: '/a' });
    const g = ix('graphql', { description: 'g', graphqlQuery: '', graphqlVariables: '[1]' });
    const r = ix('grpc', { description: 'r', service: 'nope' });
    const problems = draftProblems({ consumer: 'A', provider: 'B', interactions: [a, b, g, r] });
    expect(problems.interactions[a.id]).toEqual(['Put query parameters under Query, not in the path.']);
    expect(problems.interactions[b.id]).toEqual(['Interaction 1 has the same description and provider states: a verifier could not tell them apart.']);
    expect(problems.interactions[g.id]).toEqual(['Write the GraphQL operation.', 'Variables are a JSON object.']);
    expect(problems.interactions[r.id]).toEqual(['Name the call as package.Service/Method.']);
  });

  it('needs at least one interaction', () => {
    expect(draftProblems({ consumer: 'A', provider: 'B', interactions: [] }).pair).toEqual(['Add an interaction.']);
  });

  it.each([
    [{ path: 'id', match: 'type', argument: '' }, 'id is not a field path such as $.id or $.items[*].id.'],
    [{ path: '$.a', match: 'regex', argument: '' }, '$.a: a regex matcher needs a pattern.'],
    [{ path: '$.a', match: 'regex', argument: '(' }, '$.a: ( is not a valid pattern.'],
    [{ path: '$.a', match: 'date', argument: '' }, '$.a: a date matcher needs a format, e.g. yyyy-MM-dd.'],
    [{ path: '$.a', match: 'include', argument: '' }, '$.a: an include matcher needs the text to look for.'],
    [{ path: '$.a', match: 'minType', argument: 'x' }, '$.a: min needs a whole number of items.'],
  ] as const)('matcher %j: %s', (matcher, problem) => {
    expect(matcherProblem({ ...matcher })).toBe(problem);
  });

  it('accepts every path form the spec writes', () => {
    for (const path of ['$', '$.id', '$.items[*].id', '$.items[0]', "$['odd key']"]) {
      expect(matcherProblem({ path, match: 'type', argument: '' })).toBeNull();
    }
  });
});

describe('provider-state parameters', () => {
  it('reads JSON values as JSON and the rest as text, commas inside quotes and brackets kept', () => {
    expect(parseStateParams('id = 42, name = Ada Lovelace, tags = ["a", "b"], note = "x, y", ok = true')).toEqual({
      params: { id: 42, name: 'Ada Lovelace', tags: ['a', 'b'], note: 'x, y', ok: true },
    });
    expect(parseStateParams('')).toEqual({ params: {} });
    expect(parseStateParams('id = 1, id = 2')).toEqual({ error: 'id is given twice.' });
  });

  it('writes values back so they read the same', () => {
    const params = { id: 42, code: '42', name: 'Ada', empty: '', comma: 'a, b', yes: 'true', list: [1] };
    const text = formatStateParams(params);
    expect(text).toBe('id = 42, code = "42", name = Ada, empty = "", comma = "a, b", yes = "true", list = [1]');
    expect(parseStateParams(text)).toEqual({ params });
  });
});

describe('the spec', () => {
  const operations: SpecOperation[] = [
    {
      method: 'GET',
      path: '/invoices/{id}',
      summary: 'Get an invoice',
      responses: [
        {
          status: '200',
          contentType: 'application/json',
          example: { id: 42, currency: 'EUR' },
          exampleSource: 'spec',
          fields: [
            { path: '$.id', type: 'integer' },
            { path: '$.currency', type: 'string', pattern: '^[A-Z]{3}$' },
          ],
        },
        { status: '404', contentType: null, exampleSource: 'none', fields: [] },
      ],
    },
    { method: 'GET', path: '/invoices/latest', summary: null, responses: [{ status: '200', contentType: 'application/json', example: {}, exampleSource: 'schema', fields: [] }] },
    { method: 'POST', path: '/invoices', summary: null, responses: [] },
  ];

  it('matches a concrete path to its template, the literal one first', () => {
    const flag = specFlag(ix('http', { method: 'GET', path: '/invoices/42' }), operations, '2.7.0');
    expect(flag.state === 'match' && flag.operation.path).toBe('/invoices/{id}');
    const literal = specFlag(ix('http', { method: 'GET', path: '/invoices/latest' }), operations, '2.7.0');
    expect(literal.state === 'match' && literal.operation.path).toBe('/invoices/latest');
  });

  it('flags a path that is not in the spec — and the pact still builds', () => {
    const missing = ix('http', { description: 'credit notes', method: 'GET', path: '/credit-notes/1' });
    expect(specFlag(missing, operations, '2.7.0')).toEqual({
      state: 'not-in-spec',
      message: 'GET /credit-notes/1 is not in the spec in 2.7.0. It can still be published; the comparison will report it.',
    });
    expect(specFlag(ix('http', { method: 'DELETE', path: '/invoices' }), operations, null)).toEqual({
      state: 'not-in-spec',
      message: '/invoices is in the spec for POST, not DELETE. It can still be published; the comparison will report it.',
    });
    expect('pact' in buildPact({ consumer: 'A', provider: 'B', interactions: [missing] })).toBe(true);
  });

  it('does not check messages, gRPC, or without a spec', () => {
    expect(specFlag(ix('message', {}), operations, null).state).toBe('unchecked');
    expect(specFlag(ix('grpc', {}), operations, null).state).toBe('unchecked');
    expect(specFlag(ix('http', { path: '/x' }), null, null)).toEqual({ state: 'unchecked', message: 'No spec to check the path against.' });
  });

  it('fills the response from the spec: status, content type, example and matchers', () => {
    const target = ix('http', { method: 'GET', path: '/invoices/42', responseHeaders: [{ name: 'content-type', value: 'text/plain' }, { name: 'X-Trace', value: '1' }] });
    const answer = fillFromSpec(target, operations[0]);
    if ('error' in answer) throw new Error(answer.error);
    expect(answer.patch).toEqual({
      status: '200',
      responseHeaders: [
        { name: 'X-Trace', value: '1' },
        { name: 'Content-Type', value: 'application/json' },
      ],
      responseBody: { text: json({ id: 42, currency: 'EUR' }), contentType: 'application/json' },
      responseMatchers: [
        { path: '$.id', match: 'integer', argument: '' },
        { path: '$.currency', match: 'regex', argument: '^[A-Z]{3}$' },
      ],
    });
    expect(answer.note).toBe('Filled from the 200 response of GET /invoices/{id}: the spec’s example.');
  });

  it('takes the response with the typed status, and says when the example was generated', () => {
    const notFound = fillFromSpec(ix('http', { status: '404' }), operations[0]);
    expect('patch' in notFound && notFound.patch.responseBody.text).toBe('');
    expect('note' in notFound && notFound.note).toBe('The 404 response of GET /invoices/{id} has no body.');
    const generated = fillFromSpec(ix('http', {}), operations[1]);
    expect('note' in generated && generated.note).toContain('generated from the schema — review the values');
    expect(fillFromSpec(ix('http', {}), operations[2])).toEqual({ error: 'POST /invoices documents no response to fill from.' });
  });

  it('suggests a matcher per field type', () => {
    expect(matcherForField({ path: '$.n', type: 'number' }).match).toBe('number');
    expect(matcherForField({ path: '$.b', type: 'boolean' }).match).toBe('boolean');
    expect(matcherForField({ path: '$.l', type: 'array' })).toEqual({ path: '$.l', match: 'minType', argument: '1' });
    expect(matcherForField({ path: '$.s', type: 'string', enum: ['a.b', 'c'] })).toEqual({ path: '$.s', match: 'regex', argument: '^(a\\.b|c)$' });
    expect(matcherForField({ path: '$.d', type: 'string', format: 'date' })).toEqual({ path: '$.d', match: 'date', argument: 'yyyy-MM-dd' });
    expect(matcherForField({ path: '$.s', type: 'string' }).match).toBe('type');
  });
});

describe('adding a field the consumer needs', () => {
  it('puts the value at its path, making objects and arrays on the way', () => {
    expect(placeField('', '$.invoice.lines[*].sku', 'A-1')).toEqual({ text: json({ invoice: { lines: [{ sku: 'A-1' }] } }) });
    expect(placeField(json({ id: 1 }), '$.currency', 'EUR')).toEqual({ text: json({ id: 1, currency: 'EUR' }) });
    expect(placeField('', "$['odd key']", 1)).toEqual({ text: json({ 'odd key': 1 }) });
  });

  it('refuses a body that is not JSON or a path it cannot read', () => {
    expect(placeField('{', '$.a', 1)).toEqual({ error: 'The body is not valid JSON, so the field cannot be added to it.' });
    expect(placeField('', '$..a', 1)).toEqual({ error: '$..a is not a field path such as $.id or $.items[*].id.' });
    expect(placeField('', 'a', 1)).toEqual({ error: 'a is not a field path such as $.id.' });
  });
});

describe('the list', () => {
  it('reads each interaction by its method or kind and description', () => {
    expect(listLabel(ix('http', { method: 'post', description: 'create' }))).toEqual({ badge: 'POST', title: 'create' });
    expect(listLabel(ix('grpc', { service: 'a.B/C' }))).toEqual({ badge: 'gRPC', title: 'a.B/C' });
    expect(listLabel(ix('message', {}))).toEqual({ badge: 'Message', title: 'A message' });
  });
});

/**
 * REST payloads for the Arazzo workflow viewer tests (COA-1.3, #7039).
 *
 * Shaped exactly like `GET /v1/workflows/{tenant}/catalog/{itemId}` and
 * `…/operations/{pathOperationId}` return them (snake_case), so the tests exercise the same
 * parse the panel runs on a live response. The checkout workflow covers every routing case the
 * step graph draws: a default next step, an explicit `goto`, an `end`, a self-`retry`, a step
 * that calls another workflow, a resolved and an unresolved operation, and a resolved and a
 * missing source description.
 */

export const ITEM_ID = '11111111-1111-4111-8111-111111111111';
export const VERSION_ID = '22222222-2222-4222-8222-222222222222';
export const OP_GET_CART = '33333333-3333-4333-8333-333333333333';
export const OP_SEND_EMAIL = '44444444-4444-4444-8444-444444444444';

/** An operation summary as the workflow payload embeds it. */
function operation(id: string, method: string, path: string, operationId: string) {
  return {
    path_operation_id: id,
    method,
    path,
    path_id: `path-${id.slice(0, 4)}`,
    summary: `${method} ${path}`,
    description: null,
    operation_id: operationId,
    version_id: VERSION_ID,
    version_label: '1.4.0',
    project_id: '55555555-5555-4555-8555-555555555555',
    project_name: 'Shop API',
    project_publishable: true,
  };
}

const SHOP = {
  name: 'shop',
  url: './shop.openapi.yaml',
  type: 'openapi',
  status: 'resolved',
  tier: 'fileset',
  reason: null,
  detail: null,
};
const PAYMENTS = {
  name: 'payments',
  url: 'https://payments.example.com/openapi.yaml',
  type: 'openapi',
  status: 'missing',
  tier: null,
  reason: 'resolution-disabled',
  detail: 'Remote resolution is turned off for this import.',
};

/** A step with every list/map field defaulted, overridden by `over`. */
function step(over: Record<string, unknown>) {
  return {
    description: null,
    target_kind: 'operation',
    target_workflow_id: null,
    operation_ref: null,
    operation_id: null,
    resolution_status: 'unresolved',
    resolution_reason: 'unknown-operation',
    operation: null,
    source_names: [],
    parameters: [],
    request_body: null,
    success_criteria: [],
    on_success: [],
    on_failure: [],
    outputs: {},
    depends_on: [],
    ...over,
  };
}

/** `GET /v1/workflows/{tenant}/catalog/{itemId}` for a two-workflow checkout document. */
export const WORKFLOWS_RESPONSE = {
  version_id: VERSION_ID,
  project_id: ITEM_ID,
  sources: [SHOP, PAYMENTS],
  workflows: [
    {
      workflow_id: 'checkout',
      summary: 'Pay for a cart and send the receipt',
      description: 'Loads the cart, charges the card and emails the receipt.',
      ordinal: 0,
      inputs: {
        type: 'object',
        required: ['cartId'],
        properties: { cartId: { type: 'string' }, coupon: { type: 'string' } },
      },
      outputs: { receipt: '$steps.pay.outputs.receipt' },
      depends_on: [],
      success_actions: [],
      failure_actions: [],
      sources: [SHOP, PAYMENTS],
      steps: [
        step({
          step_id: 'load-cart',
          order_index: 0,
          description: 'Read the cart and its total.',
          operation_id: '$sourceDescriptions.shop.getCart',
          resolution_status: 'resolved',
          resolution_reason: null,
          operation: operation(OP_GET_CART, 'GET', '/carts/{cartId}', 'getCart'),
          source_names: ['shop'],
          parameters: [{ name: 'cartId', in: 'path', value: '$inputs.cartId' }],
          success_criteria: [{ condition: '$statusCode == 200' }],
          on_success: [{ name: 'to-pay', type: 'goto', stepId: 'pay' }],
          on_failure: [{ name: 'give-up', type: 'end' }],
          outputs: { total: '$response.body#/total' },
        }),
        step({
          step_id: 'pay',
          order_index: 1,
          operation_ref: '$sourceDescriptions.payments.url#/paths/~1charges/post',
          source_names: ['payments'],
          on_failure: [{ name: 'again', type: 'retry', retryAfter: 1, retryLimit: 3 }],
          outputs: { receipt: '$response.body#/id' },
        }),
        step({
          step_id: 'notify',
          order_index: 2,
          target_kind: 'workflow',
          target_workflow_id: 'send-receipt',
          resolution_status: 'not_applicable',
          resolution_reason: 'calls-workflow',
        }),
      ],
    },
    {
      workflow_id: 'send-receipt',
      summary: 'Email a receipt',
      description: null,
      ordinal: 1,
      inputs: { $ref: '#/components/inputs/receipt' },
      outputs: {},
      depends_on: [],
      success_actions: [],
      failure_actions: [],
      sources: [SHOP],
      steps: [
        step({
          step_id: 'email',
          order_index: 0,
          operation_id: '$sourceDescriptions.shop.sendEmail',
          resolution_status: 'resolved',
          resolution_reason: null,
          operation: operation(OP_SEND_EMAIL, 'POST', '/emails', 'sendEmail'),
          source_names: ['shop'],
        }),
      ],
    },
  ],
};

/** `GET /v1/workflows/{tenant}/operations/{OP_GET_CART}`. */
export const OPERATION_RESPONSE = {
  ...operation(OP_GET_CART, 'GET', '/carts/{cartId}', 'getCart'),
  summary: 'Get a cart',
  description: 'Returns the cart with its line items and total.',
  parameters: [{ name: 'cartId', in_location: 'path', description: 'The cart to read.' }],
  responses: [
    { status_code: '200', description: 'The cart' },
    { status_code: '404', description: 'No such cart' },
  ],
};

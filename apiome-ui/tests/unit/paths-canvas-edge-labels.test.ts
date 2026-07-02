import { describe, it, expect } from '@jest/globals';
import type { Node } from '@xyflow/react';
import {
  labelPathToOperation,
  labelOperationToParameter,
  labelOperationToRequestBody,
  labelOperationToResponse,
  labelForManualConnection,
} from '../../src/app/ade/studio/paths/lib/paths-canvas-edge-labels';

describe('paths-canvas-edge-labels', () => {
  it('uses roadmap role strings for primary attachments', () => {
    expect(labelPathToOperation()).toBe('');
    expect(labelOperationToParameter()).toBe('hasParam');
    expect(labelOperationToRequestBody()).toBe('requestBody');
    expect(labelOperationToResponse('200')).toBe('response 200');
    expect(labelOperationToResponse('404', 'application/json')).toBe('response 404 · application/json');
    expect(labelOperationToRequestBody('application/json')).toBe('requestBody · application/json');
  });

  it('labelForManualConnection covers operation ↔ attachment pairs', () => {
    const op = { id: 'op1', type: 'operation', data: { dbOperationId: 'op1', statusCode: 'GET' } } as Node;
    const param = { id: 'p1', type: 'parameter', data: {} } as Node;
    const resp = { id: 'r1', type: 'response', data: { statusCode: '201' } } as Node;
    const rb = { id: 'rb1', type: 'requestBody', data: { id: 'rb-db' } } as Node;
    const path = { id: 'path1', type: 'pathTemplate', data: {} } as Node;

    expect(labelForManualConnection(op, param)?.semantic).toBe('operation-has-parameter');
    expect(labelForManualConnection(param, op)?.semantic).toBe('operation-has-parameter');
    expect(labelForManualConnection(op, resp)?.label).toBe('response 201');
    expect(labelForManualConnection(resp, op)?.label).toBe('response 201');
    expect(labelForManualConnection(op, rb)?.label).toBe('requestBody');
    expect(labelForManualConnection(rb, op)?.label).toBe('requestBody');
    expect(labelForManualConnection(path, op)?.label).toBe('');
  });
});

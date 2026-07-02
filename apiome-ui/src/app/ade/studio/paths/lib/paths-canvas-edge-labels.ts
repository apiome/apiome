/** Presentational labels for Path Designer canvas edges (P-07 / #2646). OpenAPI export ignores geometry. */

import type { Node } from '@xyflow/react';

export type PathsCanvasEdgeSemantic =
  | 'path-has-operation'
  | 'operation-has-parameter'
  | 'operation-has-request-body'
  | 'operation-has-response'
  | 'response-has-body'
  | 'response-has-class';

export function labelPathToOperation(): string {
  return '';
}

export function labelOperationToParameter(): string {
  return 'hasParam';
}

export function labelOperationToRequestBody(mediaTypeSummary?: string): string {
  if (mediaTypeSummary) return `requestBody · ${mediaTypeSummary}`;
  return 'requestBody';
}

export function labelOperationToResponse(statusCode: string, mediaTypeSummary?: string): string {
  const code = String(statusCode ?? '').trim() || '?';
  const base = `response ${code}`;
  if (mediaTypeSummary) return `${base} · ${mediaTypeSummary}`;
  return base;
}

export const pathsCanvasEdgeLabelStyle = {
  fontSize: 10,
  fill: '#334155',
} as const;

export const pathsCanvasEdgeLabelBgStyle = {
  fill: '#f1f5f9',
  stroke: '#94a3b8',
} as const;

/** Labels for user-drawn edges (manual reconnect). */
export function labelForManualConnection(
  sourceNode: Node | undefined,
  targetNode: Node | undefined
): { label: string; semantic: PathsCanvasEdgeSemantic } | null {
  if (sourceNode?.type === 'pathTemplate' && targetNode?.type === 'operation') {
    return { label: labelPathToOperation(), semantic: 'path-has-operation' };
  }
  if (sourceNode?.type === 'operation' && targetNode?.type === 'pathTemplate') {
    return { label: labelPathToOperation(), semantic: 'path-has-operation' };
  }
  if (
    (sourceNode?.type === 'operation' && targetNode?.type === 'parameter') ||
    (sourceNode?.type === 'parameter' && targetNode?.type === 'operation')
  ) {
    return { label: labelOperationToParameter(), semantic: 'operation-has-parameter' };
  }
  if (sourceNode?.type === 'operation' && targetNode?.type === 'response') {
    const code = String((targetNode.data as { statusCode?: string })?.statusCode ?? '').trim() || '?';
    return { label: labelOperationToResponse(code), semantic: 'operation-has-response' };
  }
  if (sourceNode?.type === 'response' && targetNode?.type === 'operation') {
    const code = String((sourceNode.data as { statusCode?: string })?.statusCode ?? '').trim() || '?';
    return { label: labelOperationToResponse(code), semantic: 'operation-has-response' };
  }
  if (
    (sourceNode?.type === 'operation' && targetNode?.type === 'requestBody') ||
    (sourceNode?.type === 'requestBody' && targetNode?.type === 'operation')
  ) {
    return { label: labelOperationToRequestBody(), semantic: 'operation-has-request-body' };
  }
  return null;
}

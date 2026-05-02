import type { McpErrorCode } from './types.js';

export type UpstreamError = {
  code: McpErrorCode;
  message: string;
  cause?: unknown;
};

/** Maps REST / transport failures into MCP-facing codes (expanded in MCP-2.6). */
export function toUpstreamError(err: unknown): UpstreamError {
  if (err && typeof err === 'object' && 'message' in err && typeof (err as Error).message === 'string') {
    return { code: 'UPSTREAM_ERROR', message: (err as Error).message, cause: err };
  }
  return { code: 'UPSTREAM_ERROR', message: 'Unknown upstream error', cause: err };
}

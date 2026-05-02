import type { JsonSchema } from './json-schema.js';

export type ActionContext = {
  tenantId?: string;
};

export type ActionDescriptor = {
  id: string;
  category?: string;
  description?: string;
  resource?: string;
  requiredScopes?: string[];
};

export type ActionDescribeResult = {
  actionId: string;
  inputSchema: JsonSchema;
  outputSchema: JsonSchema;
};

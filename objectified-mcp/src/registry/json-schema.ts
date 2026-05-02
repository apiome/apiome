/** Minimal JSON Schema typing for describe payloads (draft-2020-12 subset). */
export type JsonSchema = {
  type?: string | string[];
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  items?: JsonSchema;
  enum?: unknown[];
  [key: string]: unknown;
};

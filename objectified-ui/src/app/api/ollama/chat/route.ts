/**
 * API route to chat with Ollama using Server-Sent Events (SSE)
 */

import { NextRequest } from 'next/server';
import { isAbortError } from '../../../ade/studio/components/chatbot/abort-errors';

const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || 'http://localhost:11434';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function usageFromOllamaPayload(data: Record<string, unknown>): { promptTokens?: number; completionTokens?: number } | undefined {
  const p = data.prompt_eval_count;
  const c = data.eval_count;
  const usage: { promptTokens?: number; completionTokens?: number } = {};
  if (typeof p === 'number') usage.promptTokens = p;
  if (typeof c === 'number') usage.completionTokens = c;
  return Object.keys(usage).length > 0 ? usage : undefined;
}

function pickAssistantContent(data: Record<string, unknown>): string | undefined {
  const message = data.message;
  if (!message || typeof message !== 'object') return undefined;
  const raw = (message as { content?: unknown }).content;
  return typeof raw === 'string' && raw.length > 0 ? raw : undefined;
}

const CLASS_SKELETON_SYSTEM = `You are an expert at defining JSON Schema (OpenAPI 3.1) class/schema definitions. The user will describe a class they want to create. Your only job is to output a single JSON code block that defines that class.

# Output format

Respond with exactly one JSON code block in this shape:
\`\`\`json
{
  "name": "ClassName",
  "description": "Optional short description of the class",
  "schema": {
    "type": "object",
    "properties": { ... },
    "required": [ ... ]
  }
}
\`\`\`

# Rules

- "name" must be PascalCase and contain only letters, numbers, and underscores (A-Za-z0-9_).
- "schema" must be a valid JSON Schema object. It must include "type": "object" and a "properties" object (can be empty {} for a placeholder).
- You may use any JSON Schema / OpenAPI 3.1 schema features in "schema": properties, required, allOf, anyOf, oneOf, discriminator, additionalProperties, unevaluatedProperties, patternProperties, dependentSchemas, dependentRequired, deprecated, deprecationMessage, minProperties, maxProperties, examples, xml, $id, $anchor, $comment, externalDocs, if/then/else, and x-* extensions.
- For $ref inside the schema, use format "#/components/schemas/ClassName" when referencing other classes.
- Property names in "properties" should be camelCase. Include "description" (and optionally "summary") on the schema and on properties where helpful.
- Keep the class a clear skeleton: include the structure the user asked for, but you do not need to exhaust every option. Prefer properties and required; add allOf/anyOf/oneOf/discriminator/additionalProperties etc. only when they fit the user's description.
- Do not output any text outside the single JSON code block. No commentary before or after.`;

function buildClassSkeletonSystem(options: {
  existingClassNames?: string[];
  existingProperties?: Array<{ name: string; description?: string | null; data?: Record<string, unknown> }>;
}): string {
  let extra = '';
  if (options.existingClassNames?.length) {
    extra += `\n\n# Existing classes in this version (reference with $ref: "#/components/schemas/ClassName")\n${options.existingClassNames.join(', ')}`;
  }
  if (options.existingProperties?.length) {
    extra += `\n\n# Existing project properties (reuse by using the exact "name" in your schema.properties; these are shared across classes)\n`;
    options.existingProperties.forEach((p) => {
      const d = p.data;
      const typeStr =
        typeof d?.type === 'string'
          ? d.type
          : d && '$ref' in d && d.$ref
            ? `$ref`
            : 'object';
      extra += `- ${p.name}: ${typeStr}${p.description ? ` — ${String(p.description).slice(0, 60)}` : ''}\n`;
    });
  }
  return CLASS_SKELETON_SYSTEM + extra;
}

const DATA_QUERY_SYSTEM = `You are an expert at helping users query and search structured data. The user is asking questions about data stored in tables (each table corresponds to a class/schema in their version). Your job is to:

1. Interpret their natural language question.
2. Suggest how to find the data: e.g. which table(s) to look at, what field or criteria might match (e.g. "search for records where name contains X", "filter by status = active").
3. If they ask for something that would require a specific query or filter, describe the filter or search in plain language and optionally as a simple JSON structure (e.g. { "field": "name", "op": "contains", "value": "..." }).

You do NOT have direct access to run queries. You are assisting the user to formulate their search. Be concise. If the user's question is ambiguous, ask for clarification. Vectorization and semantic search may be added later; for now suggest keyword or field-based search.`;

function buildDataQuerySystem(options: { tableNames?: string[]; currentTableName?: string }): string {
  let s = DATA_QUERY_SYSTEM;
  if (options.tableNames?.length) {
    s += `\n\n# Available tables in this version\n${options.tableNames.join(', ')}`;
  }
  if (options.currentTableName) {
    s += `\n\n# Table currently selected by the user\n${options.currentTableName}`;
  }
  return s;
}

export async function POST(request: NextRequest) {
  try {
    const { model, messages, task, existingClassNames, existingProperties, tableNames, currentTableName } = await request.json();

    if (!model || !messages || !Array.isArray(messages)) {
      return new Response(
        JSON.stringify({ error: 'Invalid request: model and messages are required' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    }

    const isClassSkeleton = task === 'class_skeleton';
    const isDataQuery = task === 'data_query';

    // Create a system message to guide the LLM
    const systemContent = isClassSkeleton
      ? buildClassSkeletonSystem({
          existingClassNames: Array.isArray(existingClassNames) ? existingClassNames : undefined,
          existingProperties: Array.isArray(existingProperties) ? existingProperties : undefined,
        })
      : isDataQuery
        ? buildDataQuerySystem({
            tableNames: Array.isArray(tableNames) ? tableNames : undefined,
            currentTableName: typeof currentTableName === 'string' ? currentTableName : undefined,
          })
        : `You are an expert API designer and OpenAPI specification generator. Your task is to help users create OpenAPI 3.1.0 specifications based on their natural language descriptions.

# Rules

- Always generate valid OpenAPI 3.1.0 specifications
- When generating a complete specification, wrap it in a JSON code block: \`\`\`json\n{spec}\n\`\`\`
- Include proper info section with title, version, description, license, contact details
- Add servers section with at least one server URL (localhost is fine), and tags section with relevant tags
- Generate only schemas. Do not generate paths.
- Use components/schemas for all schema definitions
- Include appropriate HTTP methods and response codes
- Always generate descriptions and summaries to all properties and schemas
- Encourage using $ref for schema references when properties are reused
- Avoid duplicating properties: use $ref instead
- **CRITICAL: $ref must ONLY reference complete schemas in #/components/schemas, NEVER individual properties within a schema**
- **CORRECT: { "$ref": "#/components/schemas/User" }**
- When you need to reference a class/schema, use: "#/components/schemas/ClassName"
- Use advanced schema features like patternProperties, discriminators, conditional rules, and allOf/oneOf/anyOf where applicable
- Be conversational and explain your design decisions
- Support incremental improvements to existing specs
- Do not generate clips of schemas in the response: The output should be the final schema
- Do not make up rules or paths that are not possible in OpenAPI 3.1.0

# Generation instructions

- Do not output or generate paths.
- Only generate a complete OpenAPI Specification with a \`#/components/schemas\` section.
- Schemas must include a summary and description
- Examples must be provided for all schemas and properties of type "object" where applicable, and must be "examples" as an array, not singular "example"
- Property names are camelCase
- Schema and Tag names are PascalCase
- Objects cannot be outside of the properties definitions - all objects must contain properties unless they are allOf/oneOf/anyOf discriminators
- **$ref MUST reference complete schemas only**: Use "#/components/schemas/ClassName" format

# Important

- Schema must contain "openapi: 3.1.0" at the root level
- Properties must be defined in the properties section of the schema, and cannot reference a type outside of the schema like "#/components/schemas/User/properties/email" or "#/components/schemas/User#/properties/email". Instead, use "#/components/schemas/Email" or "#/components/schemas/Phone" respectively.
- All properties must include summaries and descriptions
- All classes must include summaries and descriptions
- All properties of type "object" must include examples
- All classes must include examples
- Examples must be provided in an "examples" array

Make adjustments to the schema as needed based on user feedback and requests for changes.  Provide no additional feedback,
commentary, or thinking output.`;

    const systemMessage = {
      role: 'system',
      content: systemContent,
    };

    // Prepare messages with system prompt
    const fullMessages = [systemMessage, ...messages];

    // Make request to Ollama with streaming
    const ollamaResponse = await fetch(`${OLLAMA_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model,
        messages: fullMessages,
        stream: true,
      }),
      signal: request.signal,
    });

    if (!ollamaResponse.ok) {
      throw new Error(`Ollama API error: ${ollamaResponse.statusText}`);
    }

    // Create a ReadableStream to process the streaming response
    const encoder = new TextEncoder();
    const decoder = new TextDecoder();

    const stream = new ReadableStream({
      async start(controller) {
        const reader = ollamaResponse.body?.getReader();
        if (!reader) {
          controller.close();
          return;
        }

        let closed = false;

        function safeEnqueue(data: Uint8Array): boolean {
          if (closed) return false;
          try {
            controller.enqueue(data);
            return true;
          } catch (e) {
            if (e instanceof TypeError && String(e.message).includes('already closed')) {
              closed = true;
              return false;
            }
            throw e;
          }
        }

        function safeClose(): void {
          if (closed) return;
          try {
            controller.close();
            closed = true;
          } catch (e) {
            if (e instanceof TypeError && String(e.message).includes('already closed')) {
              closed = true;
            } else {
              throw e;
            }
          }
        }

        let buffer = '';

        try {
          while (true) {
            const { done, value } = await reader.read();

            if (done) {
              // Process any remaining buffer
              if (buffer.trim() && !closed) {
                try {
                  const data = JSON.parse(buffer) as Record<string, unknown>;
                  const content = pickAssistantContent(data);
                  const usage = usageFromOllamaPayload(data);
                  const isDone = Boolean(data.done);
                  if (content || usage) {
                    const event: Record<string, unknown> = { done: isDone };
                    if (content) event.content = content;
                    if (usage) event.usage = usage;
                    safeEnqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
                  }
                } catch {
                  // Ignore parse errors on final buffer
                }
              }

              if (!closed) {
                safeEnqueue(encoder.encode('data: [DONE]\n\n'));
                safeClose();
              }
              break;
            }

            // Decode the chunk with streaming enabled
            const chunk = decoder.decode(value, { stream: true });
            buffer += chunk;

            // Process complete lines immediately (split by newline)
            const lines = buffer.split('\n');

            // Keep the last incomplete line in the buffer
            buffer = lines.pop() || '';

            // Process each complete line immediately
            for (const line of lines) {
              if (!line.trim() || closed) continue;

              try {
                const data = JSON.parse(line) as Record<string, unknown>;
                const content = pickAssistantContent(data);
                const usage = usageFromOllamaPayload(data);
                const isDone = Boolean(data.done);

                if (content || usage) {
                  const event: Record<string, unknown> = { done: isDone };
                  if (content) event.content = content;
                  if (usage) event.usage = usage;
                  if (!safeEnqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))) {
                    break;
                  }
                }

                // If this is the last message, signal completion
                if (isDone) {
                  safeEnqueue(encoder.encode('data: [DONE]\n\n'));
                  safeClose();
                  return;
                }
              } catch (parseError) {
                // Only log actual JSON parse errors, not controller-closed from client disconnect
                if (parseError instanceof SyntaxError || (parseError instanceof TypeError && !String(parseError.message).includes('already closed'))) {
                  console.error('Error parsing Ollama response line:', parseError, 'Line:', line);
                }
              }
            }
          }
        } catch (error) {
          if (!closed) {
            if (!isAbortError(error, request.signal)) {
              console.error('Error reading stream:', error);
            }
            try {
              controller.error(error);
            } catch {
              // Controller may already be closed (e.g. client disconnected)
            }
          }
        }
      },
    });

    // Return SSE response
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });
  } catch (error: unknown) {
    // AbortError is normal (client disconnected or user clicked Stop) — don't log or 500.
    if (isAbortError(error, request.signal)) {
      return new Response(null, { status: 499 });
    }
    console.error('Error in Ollama chat:', error);
    const message = error instanceof Error ? error.message : 'Failed to process chat request';
    return new Response(
      JSON.stringify({ error: message || 'Failed to process chat request' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } }
    );
  }
}


import { looksLikeStructuredDocument } from './document-markers';
/**
 * Protobuf (.proto) to OpenAPI 3.1.x Converter (for Import) — #238
 *
 * Converts Protocol Buffer definition files to an OpenAPI 3.1–shaped document
 * so the existing import pipeline (components.schemas, $ref) can be reused.
 *
 * - message definitions → object schemas
 * - enum definitions → string schemas with enum array
 * - repeated → array of item type
 * - map<K,V> → object with additionalProperties
 * - oneof → each member stays an (optional) property tagged `x-proto-oneof: <group>`; the message schema
 *   lists its groups under `x-proto-oneofs` (`{ group: [member, …] }`) — at most one member is set (#2776)
 */

/** The property extension naming the `oneof` group a field belongs to (#2776). */
export const PROTO_ONEOF_EXTENSION = 'x-proto-oneof';

/** The message-schema extension listing each `oneof` group and its members, in declaration order (#2776). */
export const PROTO_ONEOFS_EXTENSION = 'x-proto-oneofs';

export interface ProtobufConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

const PROTO_SCALAR_TO_JSON: Record<string, { type: string; format?: string }> = {
  double: { type: 'number', format: 'double' },
  float: { type: 'number', format: 'float' },
  int32: { type: 'integer', format: 'int32' },
  int64: { type: 'integer', format: 'int64' },
  uint32: { type: 'integer', format: 'int32' },
  uint64: { type: 'integer', format: 'int64' },
  sint32: { type: 'integer', format: 'int32' },
  sint64: { type: 'integer', format: 'int64' },
  fixed32: { type: 'integer', format: 'int32' },
  fixed64: { type: 'integer', format: 'int64' },
  sfixed32: { type: 'integer', format: 'int32' },
  sfixed64: { type: 'integer', format: 'int64' },
  bool: { type: 'boolean' },
  string: { type: 'string' },
  bytes: { type: 'string', format: 'byte' },
};

/**
 * Detect if the content looks like a Protocol Buffers (.proto) definition.
 */
export function isProtobuf(content: string): boolean {
  if (!content || typeof content !== 'string') return false;
  const trimmed = content.trim();
  // A JSON or YAML document is never Protobuf, whatever words its descriptions use.
  if (looksLikeStructuredDocument(trimmed)) return false;
  // syntax = "proto2" or "proto3"
  if (/^\s*syntax\s*=\s*["']proto(2|3)["']\s*;/.test(trimmed)) return true;
  // Common .proto patterns: message X { or enum X {
  if (/\bmessage\s+[\w.]+\s*\{/.test(trimmed)) return true;
  if (/\benum\s+[\w.]+\s*\{/.test(trimmed)) return true;
  return false;
}

function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\/\/[^\n]*/g, ' ');
}

function findMatchingBrace(s: string, start: number): number {
  let depth = 1;
  let i = start;
  while (i < s.length && depth > 0) {
    const c = s[i];
    if (c === '{') depth++;
    else if (c === '}') depth--;
    i++;
  }
  return depth === 0 ? i - 1 : -1;
}

interface ProtoEnum {
  name: string;
  fullName: string;
  values: string[];
}

interface ProtoMessage {
  name: string;
  fullName: string;
  fields: Array<{
    name: string;
    modifier?: 'optional' | 'required' | 'repeated';
    kind: 'scalar' | 'enum' | 'message' | 'repeated' | 'map';
    scalar?: string;
    refType?: string;
    keyType?: string;
    valueType?: string;
    number: number;
    /** The `oneof` group the field is declared in, when it is (#2776). */
    oneof?: string;
  }>;
  nested: Array<ProtoMessage | ProtoEnum>;
}

/**
 * The `oneof` groups a message body declares at its own level — not those of a message or enum nested in it.
 *
 * @param inner - The message body (between its braces).
 * @returns Field name → the `oneof` group it is declared in.
 */
function parseOneofGroups(inner: string): Map<string, string> {
  // The spans of nested message / enum blocks, whose oneofs belong to the nested message.
  const nested: Array<[number, number]> = [];
  const nestedRegex = /\b(?:message|enum)\s+\w+\s*\{/g;
  let nestedMatch;
  while ((nestedMatch = nestedRegex.exec(inner)) !== null) {
    const open = nestedMatch.index + nestedMatch[0].length - 1;
    const close = findMatchingBrace(inner, open + 1);
    if (close !== -1) nested.push([open, close]);
  }
  const insideNested = (index: number) => nested.some(([open, close]) => index > open && index < close);

  const groups = new Map<string, string>();
  const oneofRegex = /\boneof\s+(\w+)\s*\{/g;
  let oneofMatch;
  while ((oneofMatch = oneofRegex.exec(inner)) !== null) {
    if (insideNested(oneofMatch.index)) continue;
    const open = oneofMatch.index + oneofMatch[0].length - 1;
    const close = findMatchingBrace(inner, open + 1);
    if (close === -1) continue;
    const memberRegex = /(?:map\s*<[^>]*>|\w+)\s+(\w+)\s*=\s*\d+\s*;/g;
    let memberMatch;
    while ((memberMatch = memberRegex.exec(inner.slice(open + 1, close))) !== null) {
      groups.set(memberMatch[1], oneofMatch[1]);
    }
  }
  return groups;
}

function parseProtoEnumsAndMessages(
  body: string,
  prefix: string,
  allEnums: Map<string, ProtoEnum>,
  allMessages: Map<string, ProtoMessage>,
  warnings: string[]
): void {
  const enumRegex = /\benum\s+(\w+)\s*\{/g;
  const messageRegex = /\bmessage\s+(\w+)\s*\{/g;
  let match;

  const enumMatches: Array<{ name: string; start: number }> = [];
  while ((match = enumRegex.exec(body)) !== null) {
    enumMatches.push({ name: match[1], start: match.index + match[0].length });
  }
  const messageMatches: Array<{ name: string; start: number }> = [];
  while ((match = messageRegex.exec(body)) !== null) {
    messageMatches.push({ name: match[1], start: match.index + match[0].length });
  }

  const blocks: Array<{ type: 'enum' | 'message'; name: string; start: number; rawStart: number }> = [];
  enumMatches.forEach((m) => {
    const open = body.indexOf('{', m.start - 1);
    const close = findMatchingBrace(body, open + 1);
    if (close === -1) return;
    blocks.push({
      type: 'enum',
      name: m.name,
      start: open,
      rawStart: body.lastIndexOf('enum', open) - 5,
    });
  });
  messageMatches.forEach((m) => {
    const open = body.indexOf('{', m.start - 1);
    const close = findMatchingBrace(body, open + 1);
    if (close === -1) return;
    blocks.push({
      type: 'message',
      name: m.name,
      start: open,
      rawStart: body.lastIndexOf('message', open) - 7,
    });
  });

  blocks.sort((a, b) => a.rawStart - b.rawStart);

  for (const block of blocks) {
    const open = body.indexOf('{', block.start);
    const close = findMatchingBrace(body, open + 1);
    if (close === -1) continue;
    const inner = body.slice(open + 1, close);

    const fullName = prefix ? `${prefix}_${block.name}` : block.name;

    if (block.type === 'enum') {
      const values: string[] = [];
      const optionRegex = /(\w+)\s*(=\s*-?[\w.]+)?\s*[,;]/g;
      let optMatch;
      while ((optMatch = optionRegex.exec(inner)) !== null) {
        values.push(optMatch[1]);
      }
      allEnums.set(fullName, { name: block.name, fullName, values });
    } else {
      const fields: ProtoMessage['fields'] = [];
      const fieldLineRegex =
        /(optional|repeated|required)?\s*(map\s*<\s*(\w+)\s*,\s*(\w+)\s*>|(\w+))\s+(\w+)\s*=\s*(\d+)\s*;/g;
      let lineMatch;
      while ((lineMatch = fieldLineRegex.exec(inner)) !== null) {
        const modifier = (lineMatch[1] as 'optional' | 'repeated' | 'required' | undefined) ?? undefined;
        const typePart = lineMatch[2];
        const fieldName = lineMatch[6];
        const fieldNum = parseInt(lineMatch[7], 10);

        if (typePart.startsWith('map')) {
          const keyType = lineMatch[3];
          const valueType = lineMatch[4];
          fields.push({
            name: fieldName,
            modifier,
            kind: 'map',
            keyType,
            valueType,
            number: fieldNum,
          });
        } else {
          const typeName = lineMatch[5];
          const scalar = PROTO_SCALAR_TO_JSON[typeName];
          if (scalar) {
            fields.push({
              name: fieldName,
              modifier,
              kind: modifier === 'repeated' ? 'repeated' : 'scalar',
              scalar: typeName,
              number: fieldNum,
            });
          } else if (allEnums.has(typeName) || Array.from(allEnums.keys()).some((k) => k === typeName || k.endsWith('_' + typeName))) {
            const enumRef = allEnums.has(typeName) ? typeName : Array.from(allEnums.keys()).find((k) => k.endsWith('_' + typeName) || k === typeName);
            fields.push({
              name: fieldName,
              modifier,
              kind: modifier === 'repeated' ? 'repeated' : 'enum',
              refType: enumRef ?? typeName,
              number: fieldNum,
            });
          } else {
            const msgRef = allMessages.has(typeName) ? typeName : Array.from(allMessages.keys()).find((k) => k.endsWith('_' + typeName) || k === typeName);
            fields.push({
              name: fieldName,
              modifier,
              kind: modifier === 'repeated' ? 'repeated' : 'message',
              refType: msgRef ?? typeName,
              number: fieldNum,
            });
          }
        }
      }

      // Members of a `oneof` (#2776): at most one is set, so each is optional and carries its group.
      const oneofGroups = parseOneofGroups(inner);
      for (const field of fields) {
        const group = oneofGroups.get(field.name);
        if (group) field.oneof = group;
      }

      const msg: ProtoMessage = { name: block.name, fullName, fields, nested: [] };
      allMessages.set(fullName, msg);
      parseProtoEnumsAndMessages(inner, fullName, allEnums, allMessages, warnings);
    }
  }
}

function protoTypeToSchema(
  field: ProtoMessage['fields'][0],
  allEnums: Map<string, ProtoEnum>,
  allMessages: Map<string, ProtoMessage>
): any {
  if (field.kind === 'scalar') {
    return { ...PROTO_SCALAR_TO_JSON[field.scalar!] };
  }
  if (field.kind === 'enum') {
    const e = allEnums.get(field.refType!) ?? Array.from(allEnums.values()).find((x) => x.fullName === field.refType || x.name === field.refType);
    if (e) return { type: 'string', enum: e.values.length ? e.values : [field.refType!] };
    return { type: 'string', description: `Enum: ${field.refType}` };
  }
  if (field.kind === 'message') {
    const refName = allMessages.has(field.refType!) ? field.refType! : Array.from(allMessages.keys()).find((k) => k === field.refType || k.endsWith('_' + field.refType));
    return { $ref: `#/components/schemas/${refName ?? field.refType}` };
  }
  if (field.kind === 'repeated') {
    let items: any;
    if (field.scalar) {
      items = { ...PROTO_SCALAR_TO_JSON[field.scalar] };
    } else if (field.refType) {
      const e = allEnums.get(field.refType) ?? Array.from(allEnums.values()).find((x) => x.fullName === field.refType || x.name === field.refType);
      if (e) items = { type: 'string', enum: e.values };
      else {
        const refName = allMessages.has(field.refType) ? field.refType : Array.from(allMessages.keys()).find((k) => k === field.refType || k.endsWith('_' + field.refType));
        items = { $ref: `#/components/schemas/${refName ?? field.refType}` };
      }
    } else {
      items = { type: 'string' };
    }
    return { type: 'array', items };
  }
  if (field.kind === 'map') {
    const valueSchema = PROTO_SCALAR_TO_JSON[field.valueType!]
      ? { ...PROTO_SCALAR_TO_JSON[field.valueType!] }
      : allMessages.has(field.valueType!)
        ? { $ref: `#/components/schemas/${field.valueType}` }
        : allEnums.has(field.valueType!)
          ? { type: 'string', enum: (allEnums.get(field.valueType!)!.values as string[]) }
          : { type: 'string' };
    return { type: 'object', additionalProperties: valueSchema };
  }
  return { type: 'string' };
}

/**
 * Convert Protobuf content to an OpenAPI 3.1–like document for import.
 */
export function convertProtobufToOpenAPI(content: string, _fileName?: string): ProtobufConversionResult {
  const warnings: string[] = [];

  if (!content || typeof content !== 'string') {
    return {
      success: false,
      document: null,
      error: 'Invalid or empty Protobuf content',
      warnings: [],
    };
  }

  if (!isProtobuf(content)) {
    return {
      success: false,
      document: null,
      error: 'Content does not appear to be a Protocol Buffers definition',
      warnings: [],
    };
  }

  const cleaned = stripComments(content);
  const syntaxMatch = cleaned.match(/syntax\s*=\s*["'](proto\d)["']/);
  const protoVersion = syntaxMatch ? syntaxMatch[1] : 'proto2';
  warnings.push(`Imported from Protocol Buffers (${protoVersion}). Services and RPCs are not imported; only message and enum definitions become schemas.`);

  const allEnums = new Map<string, ProtoEnum>();
  const allMessages = new Map<string, ProtoMessage>();
  parseProtoEnumsAndMessages(cleaned, '', allEnums, allMessages, warnings);

  const schemas: Record<string, any> = {};

  for (const [name, e] of allEnums) {
    schemas[name] = {
      type: 'string',
      enum: e.values.length ? e.values : ['UNSPECIFIED'],
      description: `Enum: ${e.name}`,
    };
  }

  for (const [fullName, msg] of allMessages) {
    const properties: Record<string, any> = {};
    const required: string[] = [];
    const oneofs: Record<string, string[]> = {};
    for (const f of msg.fields) {
      const schema = protoTypeToSchema(f, allEnums, allMessages);
      properties[f.name] = f.oneof ? { ...schema, [PROTO_ONEOF_EXTENSION]: f.oneof } : schema;
      if (f.oneof) {
        (oneofs[f.oneof] ??= []).push(f.name);
      } else if (protoVersion === 'proto2' && f.modifier === 'required') {
        required.push(f.name);
      }
    }
    schemas[fullName] = {
      type: 'object',
      properties: Object.keys(properties).length ? properties : {},
      ...(required.length ? { required } : {}),
      ...(Object.keys(oneofs).length ? { [PROTO_ONEOFS_EXTENSION]: oneofs } : {}),
      description: `Message: ${msg.name}`,
    };
  }

  if (Object.keys(schemas).length === 0) {
    return {
      success: false,
      document: null,
      error: 'No message or enum definitions found in the .proto file',
      warnings,
    };
  }

  const openApiDoc = {
    openapi: '3.1.0',
    info: {
      title: 'Imported from Protocol Buffers',
      version: '1.0.0',
      description: `Converted from ${protoVersion} definition. Only message and enum types are imported.`,
    },
    components: {
      schemas,
    },
  };

  return {
    success: true,
    document: openApiDoc,
    warnings,
  };
}

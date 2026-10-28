/**
 * A structural check of an emitted `.proto` file, for the Catalog → Project journey (#6278).
 *
 * The journey used to accept any file whose name ended in `.proto`. An OpenAPI project's export
 * then wrote `.integer id = 1;` — a reference to a type that does not exist — and nothing noticed.
 * This check reads the file the way `protoc` would care about for that class of bug:
 *
 * - it declares `syntax = "proto3";` (or `"proto2"`) and its braces balance;
 * - every field and rpc type is a protobuf scalar, a `map<K, V>` of them, a message or enum the file
 *   declares, or a `google.protobuf.*` well-known type the file imports;
 * - field numbers are unique within each message.
 *
 * It is not a full parser — the repository has no JavaScript protobuf parser, and the REST suite
 * compiles emitted files with the real `buf` — but every problem it reports is one `protoc` rejects.
 */

/** The protobuf scalar keywords. */
const PROTO_SCALARS = new Set([
  'double',
  'float',
  'int32',
  'int64',
  'uint32',
  'uint64',
  'sint32',
  'sint64',
  'fixed32',
  'fixed64',
  'sfixed32',
  'sfixed64',
  'bool',
  'string',
  'bytes',
]);

/** Words that start a line inside a message but never a field. */
const NON_FIELD_KEYWORDS = new Set(['option', 'reserved', 'extensions', 'message', 'enum', 'oneof', 'extend']);

/** One message (or oneof) scope: its name and the field numbers seen in it. */
interface Scope {
  kind: 'message' | 'other';
  name: string;
  numbers: Set<number>;
}

/**
 * Remove comments and the contents of string literals, keeping line breaks.
 *
 * @param text The `.proto` source.
 * @returns The source with `//` and `/* *\/` comments blanked and every string emptied to `""`.
 */
function stripCommentsAndStrings(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ' '))
    .replace(/\/\/[^\n]*/g, '')
    .replace(/"(?:[^"\\\n]|\\.)*"/g, '""');
}

/**
 * Is `ref` a type this file can use?
 *
 * @param ref A type token as written, e.g. `int64`, `.acme.v1.Pet` or `google.protobuf.Timestamp`.
 * @param declared The simple names of every message and enum the file declares.
 * @param imports The paths the file imports.
 * @returns True for a scalar, a declared type (matched by its last segment) or an imported
 *   well-known type.
 */
function isKnownType(ref: string, declared: Set<string>, imports: Set<string>): boolean {
  if (PROTO_SCALARS.has(ref)) return true;
  const qualified = ref.replace(/^\./, '');
  const simple = qualified.split('.').pop() ?? '';
  if (qualified.startsWith('google.protobuf.')) {
    return [...imports].some((path) => path.startsWith('google/protobuf/'));
  }
  return declared.has(simple);
}

/**
 * Check an emitted `.proto` file.
 *
 * @param text The file's text.
 * @returns One human-readable line per problem; empty when the file passes.
 */
export function checkProto(text: string): string[] {
  const problems: string[] = [];
  if (!/^\s*syntax\s*=\s*"proto[23]"\s*;/m.test(text)) {
    problems.push('missing `syntax = "proto3";`');
  }
  const source = stripCommentsAndStrings(text);
  const imports = new Set([...text.matchAll(/^\s*import\s+(?:public\s+|weak\s+)?"([^"]+)"\s*;/gm)].map((m) => m[1]));
  const declared = new Set([...source.matchAll(/\b(?:message|enum)\s+([A-Za-z_]\w*)\s*\{/g)].map((m) => m[1]));

  const checkType = (ref: string, where: string): void => {
    if (!isKnownType(ref, declared, imports)) problems.push(`${where}: unknown type \`${ref}\``);
  };

  const stack: Scope[] = [];
  const lines = source.split('\n');
  lines.forEach((raw, index) => {
    const line = raw.trim();
    const where = `line ${index + 1}`;
    if (!line) return;

    const opener = /^(message|enum|service|oneof)\s+(\w+)\s*\{/.exec(line);
    if (opener) {
      const parent = stack[stack.length - 1];
      // A oneof's fields share the numbering of the message around it.
      if (opener[1] === 'oneof' && parent) stack.push(parent);
      else stack.push({ kind: opener[1] === 'message' ? 'message' : 'other', name: opener[2], numbers: new Set() });
    } else if (line.startsWith('}')) {
      if (!stack.pop()) problems.push(`${where}: unbalanced \`}\``);
      return;
    }

    const rpc = /^rpc\s+\w+\s*\(\s*(?:stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(?:stream\s+)?([\w.]+)\s*\)/.exec(line);
    if (rpc) {
      checkType(rpc[1], where);
      checkType(rpc[2], where);
      // An rpc with options opens a body of its own.
      if (line.endsWith('{')) stack.push({ kind: 'other', name: 'rpc', numbers: new Set() });
      return;
    }

    const scope = stack[stack.length - 1];
    if (opener || !scope || scope.kind !== 'message') return;
    const field = /^(?:repeated\s+|optional\s+|required\s+)?(map\s*<\s*([\w.]+)\s*,\s*([\w.]+)\s*>|[\w.]+)\s+(\w+)\s*=\s*(\d+)/.exec(line);
    if (!field || NON_FIELD_KEYWORDS.has(field[1])) return;
    if (field[2] !== undefined) {
      checkType(field[2], where);
      checkType(field[3], where);
    } else {
      checkType(field[1], where);
    }
    const number = Number(field[5]);
    if (scope.numbers.has(number)) problems.push(`${where}: field number ${number} repeats in \`${scope.name}\``);
    scope.numbers.add(number);
  });
  if (stack.length) problems.push(`unclosed \`{\` in \`${stack[stack.length - 1].name}\``);
  return problems;
}

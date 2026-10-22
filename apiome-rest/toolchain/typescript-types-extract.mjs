#!/usr/bin/env node
/**
 * TypeScript type-declaration extractor (FMT-8.1, #5462).
 *
 * Reads a JSON request from STDIN — one module, or a set of modules that import one another —
 * runs the TypeScript compiler API over it, and writes a single **neutral JSON AST** to STDOUT
 * describing every `interface`, `type` and `enum` declaration it found:
 *
 *   request:  { "files": { "<name>.ts": "<source>", ... }, "root": "<name>.ts" }
 *
 *   response: {
 *     "ok":                boolean,     // parsed with no syntax errors
 *     "typescriptVersion": string,
 *     "root":              string,
 *     "files":             [string],    // the module names, sorted
 *     "imports":           [ { "file", "module", "resolved" } ],
 *     "declarations":      [ Declaration ],
 *     "diagnostics":       [ { "file", "code", "message", "line", "column", "atEnd" } ]
 *   }
 *
 * The AST is deliberately *neutral*: it says what the source wrote — a union, a tuple, a
 * reference to a declaration in another module — and leaves every modelling decision to the
 * Python normalizer (`app.typescript_types_normalizer`). Two jobs need the type checker rather
 * than the syntax tree, and only those two use it:
 *
 *   * **resolving a reference** — which declaration (in which module) a name points at, or that
 *     it points at nothing, which is how an import from a module outside the set is reported;
 *   * **evaluating a utility or query type** — `Pick`, `Omit`, `Partial`, `Required`,
 *     `Readonly`, an indexed access (`Event['type']`) and `keyof` are computed by the checker
 *     and serialized as the shape they produce.
 *
 * Constructs outside the FMT-8.1 subset — conditional, mapped and template-literal types,
 * function and constructor types, `typeof` queries, symbol keys — are emitted as an explicit
 * `{ "kind": "unsupported", "construct": … }` node carrying their source text. The normalizer
 * turns each into a declared parsing limit; nothing here ever widens one to `any`.
 *
 * The process exits 0 on every handled outcome (including a syntax error, reported in
 * `diagnostics` with `ok: false`). A non-zero exit is reserved for a wrapper failure, with the
 * reason on STDERR. It reads nothing but STDIN and the compiler's own bundled `lib.*.d.ts`
 * files, and never touches the network.
 */

import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ts = require('typescript');

/** The virtual directory every request module is mounted under. */
const ROOT_DIR = '/apiome-src/';

/** How deep a checker-evaluated type is serialized before it is cut off as recursive. */
const MAX_TYPE_DEPTH = 8;

/** Library generics whose meaning the normalizer models directly, by name. */
const COLLECTION_TYPES = new Set([
  'Array',
  'ReadonlyArray',
  'Set',
  'ReadonlySet',
  'Map',
  'ReadonlyMap',
  'Record',
]);

/** Library utility types the checker evaluates into the shape they produce. */
const UTILITY_TYPES = new Set([
  'Pick',
  'Omit',
  'Partial',
  'Required',
  'Readonly',
  'NonNullable',
  'Exclude',
  'Extract',
]);

/** Library types that denote a primitive value the normalizer has a scalar for. */
const PRIMITIVE_LIB_TYPES = {
  Date: 'date',
  Uint8Array: 'bytes',
  ArrayBuffer: 'bytes',
  String: 'string',
  Number: 'number',
  Boolean: 'boolean',
  BigInt: 'bigint',
  Object: 'object',
};

/** Keyword type nodes -> the primitive name the AST reports. */
const KEYWORD_PRIMITIVES = {
  [ts.SyntaxKind.StringKeyword]: 'string',
  [ts.SyntaxKind.NumberKeyword]: 'number',
  [ts.SyntaxKind.BooleanKeyword]: 'boolean',
  [ts.SyntaxKind.BigIntKeyword]: 'bigint',
  [ts.SyntaxKind.NullKeyword]: 'null',
  [ts.SyntaxKind.UndefinedKeyword]: 'undefined',
  [ts.SyntaxKind.AnyKeyword]: 'any',
  [ts.SyntaxKind.UnknownKeyword]: 'unknown',
  [ts.SyntaxKind.NeverKeyword]: 'never',
  [ts.SyntaxKind.VoidKeyword]: 'void',
  [ts.SyntaxKind.ObjectKeyword]: 'object',
  [ts.SyntaxKind.SymbolKeyword]: 'symbol',
};

/** Type node kinds outside the subset -> the construct name the normalizer declares. */
const UNSUPPORTED_NODES = {
  [ts.SyntaxKind.ConditionalType]: 'conditional_type',
  [ts.SyntaxKind.InferType]: 'conditional_type',
  [ts.SyntaxKind.MappedType]: 'mapped_type',
  [ts.SyntaxKind.TemplateLiteralType]: 'template_literal_type',
  [ts.SyntaxKind.FunctionType]: 'function_type',
  [ts.SyntaxKind.ConstructorType]: 'function_type',
  [ts.SyntaxKind.TypeQuery]: 'type_query',
  [ts.SyntaxKind.ImportType]: 'type_query',
  [ts.SyntaxKind.ThisType]: 'type_query',
  [ts.SyntaxKind.TypePredicate]: 'function_type',
};

/**
 * Print the wrapper + compiler version and exit. This is the `version_probe_args` the Python
 * packaging layer runs to prove the tool loads, and the banner the startup self-check reads.
 */
function printVersionAndExit() {
  process.stdout.write(`typescript-types-extract (apiome) typescript ${ts.version}\n`);
  process.exit(0);
}

/** Read all of STDIN into a single UTF-8 string. */
function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

/**
 * Build a compiler host that serves the request's modules from memory and the compiler's own
 * `lib.*.d.ts` files from disk — and nothing else, so an `import` of a package the set does
 * not contain resolves to nothing rather than to whatever happens to be installed here.
 */
function createHost(files, options) {
  const host = ts.createCompilerHost(options, true);
  const libDir = ts.getDirectoryPath(ts.getDefaultLibFilePath(options));
  const isLib = (fileName) => fileName.startsWith(libDir);
  const virtual = (fileName) => (fileName.startsWith(ROOT_DIR) ? files[fileName.slice(ROOT_DIR.length)] : undefined);

  return {
    ...host,
    fileExists: (fileName) => virtual(fileName) !== undefined || (isLib(fileName) && host.fileExists(fileName)),
    readFile: (fileName) => virtual(fileName) ?? (isLib(fileName) ? host.readFile(fileName) : undefined),
    getSourceFile: (fileName, languageVersion) => {
      const text = virtual(fileName);
      if (text !== undefined) {
        return ts.createSourceFile(fileName, text, languageVersion, true);
      }
      return isLib(fileName) ? host.getSourceFile(fileName, languageVersion) : undefined;
    },
    getCurrentDirectory: () => ROOT_DIR,
    // A directory exists when it is the root, a lib directory, or holds a request module —
    // so a set whose members live in sub-folders (`models/order.ts`) resolves `./models/order`.
    directoryExists: (dir) => {
      const prefix = dir.endsWith('/') ? dir : `${dir}/`;
      return prefix === ROOT_DIR || dir.startsWith(libDir) || Object.keys(files).some((name) => (ROOT_DIR + name).startsWith(prefix));
    },
    getDirectories: () => [],
    realpath: (path) => path,
    writeFile: () => {},
  };
}

/** Whether a declaration lives in one of the request's own modules (not a `lib` file). */
function isUserDeclaration(declaration) {
  return declaration.getSourceFile().fileName.startsWith(ROOT_DIR);
}

/** The module name (relative to the virtual root) a node lives in. */
function moduleOf(node) {
  return node.getSourceFile().fileName.slice(ROOT_DIR.length);
}

/** A declaration's stable id: `<module>#<name>`. */
function declarationId(declaration) {
  return `${moduleOf(declaration)}#${declaration.name.text}`;
}

/** Whether a node is a top-level type declaration the AST describes. */
function isTypeDeclaration(node) {
  return (
    ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) || ts.isEnumDeclaration(node)
  );
}

/** The 1-based line of a node's first token. */
function lineOf(node) {
  const sourceFile = node.getSourceFile();
  return sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
}

/** A property name rendered as text, or `null` for a computed key the AST cannot name. */
function propertyNameText(name) {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNumericLiteral(name)) {
    return name.text;
  }
  if (ts.isPrivateIdentifier(name)) {
    return name.text;
  }
  return null;
}

/** Whether a node carries the given modifier keyword. */
function hasModifier(node, kind) {
  return Boolean(ts.canHaveModifiers(node) && ts.getModifiers(node)?.some((m) => m.kind === kind));
}

class Extractor {
  constructor(program) {
    this.program = program;
    this.checker = program.getTypeChecker();
  }

  /** The documentation comment attached to a symbol or declaration, or `null`. */
  documentation(node) {
    const symbol = node.name ? this.checker.getSymbolAtLocation(node.name) : undefined;
    const parts = symbol ? symbol.getDocumentationComment(this.checker) : [];
    const text = ts.displayPartsToString(parts).trim();
    return text || null;
  }

  /** Whether a node carries a `@deprecated` JSDoc tag. */
  deprecated(node) {
    return ts.getJSDocTags(node).some((tag) => tag.tagName.text === 'deprecated');
  }

  /** Resolve the symbol a type name points at, following import/export aliases. */
  resolveSymbol(nameNode) {
    let symbol = this.checker.getSymbolAtLocation(nameNode);
    if (symbol && symbol.flags & ts.SymbolFlags.Alias) {
      symbol = this.checker.getAliasedSymbol(symbol);
    }
    if (!symbol || symbol.flags & ts.SymbolFlags.Alias || !symbol.declarations?.length) {
      return null;
    }
    return symbol;
  }

  // --- type nodes (what the source wrote) -------------------------------------------------

  /** Serialize a type node into the neutral AST. */
  typeNode(node) {
    if (!node) {
      return { kind: 'primitive', name: 'any', implicit: true };
    }
    if (node.kind in KEYWORD_PRIMITIVES) {
      return { kind: 'primitive', name: KEYWORD_PRIMITIVES[node.kind] };
    }
    if (node.kind in UNSUPPORTED_NODES) {
      return this.unsupported(UNSUPPORTED_NODES[node.kind], node);
    }
    switch (node.kind) {
      case ts.SyntaxKind.LiteralType:
        return this.literalNode(node);
      case ts.SyntaxKind.ParenthesizedType:
      case ts.SyntaxKind.OptionalType:
        return this.typeNode(node.type);
      case ts.SyntaxKind.ArrayType:
        return { kind: 'array', element: this.typeNode(node.elementType), readonly: false };
      case ts.SyntaxKind.TupleType:
        return this.tupleNode(node);
      case ts.SyntaxKind.UnionType:
        return { kind: 'union', members: node.types.map((member) => this.typeNode(member)) };
      case ts.SyntaxKind.IntersectionType:
        return { kind: 'intersection', members: node.types.map((member) => this.typeNode(member)) };
      case ts.SyntaxKind.TypeLiteral:
        return { kind: 'object', ...this.members(node.members) };
      case ts.SyntaxKind.TypeReference:
        return this.referenceNode(node);
      case ts.SyntaxKind.TypeOperator:
        return this.operatorNode(node);
      case ts.SyntaxKind.IndexedAccessType:
        return this.evaluated('indexed_access', node);
      default:
        return this.unsupported('type_query', node);
    }
  }

  /** An explicit out-of-subset marker, carrying the source text it replaced. */
  unsupported(construct, node) {
    return { kind: 'unsupported', construct, text: node.getText().replace(/\s+/g, ' ').slice(0, 200) };
  }

  literalNode(node) {
    const literal = node.literal;
    switch (literal.kind) {
      case ts.SyntaxKind.StringLiteral:
      case ts.SyntaxKind.NoSubstitutionTemplateLiteral:
        return { kind: 'literal', value: literal.text };
      case ts.SyntaxKind.NumericLiteral:
        return { kind: 'literal', value: Number(literal.text) };
      case ts.SyntaxKind.TrueKeyword:
        return { kind: 'literal', value: true };
      case ts.SyntaxKind.FalseKeyword:
        return { kind: 'literal', value: false };
      case ts.SyntaxKind.NullKeyword:
        return { kind: 'primitive', name: 'null' };
      case ts.SyntaxKind.PrefixUnaryExpression:
        if (literal.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(literal.operand)) {
          return { kind: 'literal', value: -Number(literal.operand.text) };
        }
        return this.unsupported('type_query', node);
      default:
        return this.unsupported('type_query', node);
    }
  }

  tupleNode(node) {
    return {
      kind: 'tuple',
      elements: node.elements.map((element) => {
        if (ts.isNamedTupleMember(element)) {
          return {
            name: element.name.text,
            type: this.typeNode(element.type),
            optional: Boolean(element.questionToken),
            rest: Boolean(element.dotDotDotToken),
          };
        }
        if (ts.isRestTypeNode(element)) {
          return { name: null, type: this.typeNode(element.type), optional: false, rest: true };
        }
        return {
          name: null,
          type: this.typeNode(element),
          optional: ts.isOptionalTypeNode(element),
          rest: false,
        };
      }),
    };
  }

  operatorNode(node) {
    if (node.operator === ts.SyntaxKind.ReadonlyKeyword) {
      const inner = this.typeNode(node.type);
      if (inner.kind === 'array' || inner.kind === 'tuple') {
        return { ...inner, readonly: true };
      }
      return inner;
    }
    if (node.operator === ts.SyntaxKind.UniqueKeyword) {
      return this.unsupported('symbol_key', node);
    }
    // `keyof T`: the checker computes the literal union of T's keys.
    return this.evaluated('keyof', node);
  }

  referenceNode(node) {
    const name = ts.isIdentifier(node.typeName) ? node.typeName.text : node.typeName.getText();
    const typeArguments = (node.typeArguments ?? []).map((argument) => this.typeNode(argument));
    const symbol = this.resolveSymbol(node.typeName);
    if (!symbol) {
      return { kind: 'unresolved', name };
    }
    if (symbol.flags & ts.SymbolFlags.TypeParameter) {
      return { kind: 'typeParameter', name: symbol.name };
    }

    const declaration = symbol.declarations[0];
    if (isUserDeclaration(declaration)) {
      if (ts.isEnumMember(declaration)) {
        // `Role.Admin` used as a type is that member's literal value.
        return { kind: 'literal', value: this.checker.getConstantValue(declaration) ?? declaration.name.getText() };
      }
      if (isTypeDeclaration(declaration)) {
        return { kind: 'ref', target: declarationId(declaration), name: symbol.name, typeArguments };
      }
      return this.unsupported('type_query', node);
    }

    // A library type: a collection or primitive the normalizer models by name, or a utility the
    // checker evaluates. Anything else from `lib` (Promise, Function, …) carries no data shape.
    if (COLLECTION_TYPES.has(symbol.name)) {
      return { kind: 'lib', name: symbol.name, typeArguments };
    }
    if (symbol.name in PRIMITIVE_LIB_TYPES) {
      return { kind: 'primitive', name: PRIMITIVE_LIB_TYPES[symbol.name] };
    }
    if (UTILITY_TYPES.has(symbol.name)) {
      return this.evaluated(`utility:${symbol.name}`, node);
    }
    return this.unsupported('lib_type', node);
  }

  /**
   * A construct the checker evaluates: the node's resolved type, serialized as the shape it
   * produces, with `via` naming how it was produced so the normalizer can say so.
   */
  evaluated(via, node) {
    const type = this.checker.getTypeFromTypeNode(node);
    // The evaluated type may carry the *enclosing* alias's name (`type S = Omit<…>` names the
    // result `S`), which would serialize as a reference to itself — so its alias is skipped.
    const shape = this.typeOf(type, 0, false, true);
    if (shape.kind === 'unsupported') {
      return { ...shape, text: node.getText().replace(/\s+/g, ' ').slice(0, 200) };
    }
    return { kind: 'evaluated', via, text: node.getText().replace(/\s+/g, ' ').slice(0, 200), type: shape };
  }

  /** Serialize members of an interface body or a type literal. */
  members(members) {
    const properties = [];
    const indexSignatures = [];
    const unsupported = [];
    for (const member of members) {
      if (ts.isPropertySignature(member)) {
        const name = propertyNameText(member.name);
        if (name === null) {
          unsupported.push({ name: member.name.getText(), construct: 'symbol_key', text: member.getText().slice(0, 200) });
          continue;
        }
        properties.push({
          name,
          optional: Boolean(member.questionToken),
          readonly: hasModifier(member, ts.SyntaxKind.ReadonlyKeyword),
          type: this.typeNode(member.type),
          doc: this.documentation(member),
          deprecated: this.deprecated(member),
          line: lineOf(member),
        });
      } else if (ts.isIndexSignatureDeclaration(member)) {
        const parameter = member.parameters[0];
        indexSignatures.push({
          keyName: parameter?.name?.getText() ?? 'key',
          keyType: this.typeNode(parameter?.type),
          valueType: this.typeNode(member.type),
          readonly: hasModifier(member, ts.SyntaxKind.ReadonlyKeyword),
        });
      } else {
        const name = member.name ? member.name.getText() : null;
        unsupported.push({ name, construct: 'function_type', text: member.getText().replace(/\s+/g, ' ').slice(0, 200) });
      }
    }
    return { properties, indexSignatures, unsupported };
  }

  // --- checker types (what a utility or query evaluates to) -------------------------------

  /** Serialize a checker type into the same neutral AST the syntax walk produces. */
  typeOf(type, depth, dropUndefined = false, skipAlias = false) {
    if (depth > MAX_TYPE_DEPTH) {
      return { kind: 'unsupported', construct: 'type_query', text: this.checker.typeToString(type) };
    }
    const flags = type.flags;
    const alias = type.aliasSymbol;
    if (!skipAlias && alias?.declarations?.length && isUserDeclaration(alias.declarations[0]) && isTypeDeclaration(alias.declarations[0])) {
      return {
        kind: 'ref',
        target: declarationId(alias.declarations[0]),
        name: alias.name,
        typeArguments: (type.aliasTypeArguments ?? []).map((argument) => this.typeOf(argument, depth + 1)),
      };
    }
    if (flags & ts.TypeFlags.StringLiteral || flags & ts.TypeFlags.NumberLiteral) {
      return { kind: 'literal', value: type.value };
    }
    if (flags & ts.TypeFlags.BooleanLiteral) {
      return { kind: 'literal', value: this.checker.typeToString(type) === 'true' };
    }
    if (flags & ts.TypeFlags.EnumLiteral && type.symbol) {
      return { kind: 'literal', value: type.value ?? type.symbol.name };
    }
    for (const [flag, name] of [
      [ts.TypeFlags.String, 'string'],
      [ts.TypeFlags.Number, 'number'],
      [ts.TypeFlags.Boolean, 'boolean'],
      [ts.TypeFlags.BigInt, 'bigint'],
      [ts.TypeFlags.Null, 'null'],
      [ts.TypeFlags.Undefined, 'undefined'],
      [ts.TypeFlags.Any, 'any'],
      [ts.TypeFlags.Unknown, 'unknown'],
      [ts.TypeFlags.Never, 'never'],
      [ts.TypeFlags.Void, 'void'],
    ]) {
      if (flags & flag) {
        return { kind: 'primitive', name };
      }
    }
    if (flags & ts.TypeFlags.Union) {
      return this.unionOf(type, depth, dropUndefined);
    }
    if (flags & ts.TypeFlags.Intersection) {
      return { kind: 'intersection', members: type.types.map((member) => this.typeOf(member, depth + 1)) };
    }
    if (flags & ts.TypeFlags.Object) {
      return this.objectOf(type, depth);
    }
    return { kind: 'unsupported', construct: 'type_query', text: this.checker.typeToString(type) };
  }

  /**
   * A checker union, folding the `true | false` pair back into `boolean`, and dropping
   * `undefined` when the caller already records optionality.
   */
  unionOf(type, depth, dropUndefined) {
    const members = [];
    let booleans = 0;
    for (const member of type.types) {
      if (dropUndefined && member.flags & ts.TypeFlags.Undefined) {
        continue;
      }
      if (member.flags & ts.TypeFlags.BooleanLiteral) {
        booleans += 1;
        continue;
      }
      members.push(this.typeOf(member, depth + 1));
    }
    if (booleans === 2) {
      members.push({ kind: 'primitive', name: 'boolean' });
    } else if (booleans === 1) {
      const literal = type.types.find((member) => member.flags & ts.TypeFlags.BooleanLiteral);
      members.push({ kind: 'literal', value: this.checker.typeToString(literal) === 'true' });
    }
    return members.length === 1 ? members[0] : { kind: 'union', members };
  }

  /** A checker object type: a declaration reference, a collection, or an anonymous shape. */
  objectOf(type, depth) {
    const symbol = type.symbol;
    const declaration = symbol?.declarations?.[0];
    if (declaration && isUserDeclaration(declaration) && isTypeDeclaration(declaration)) {
      return {
        kind: 'ref',
        target: declarationId(declaration),
        name: symbol.name,
        typeArguments: (type.target ? this.checker.getTypeArguments(type) : []).map((argument) =>
          this.typeOf(argument, depth + 1),
        ),
      };
    }
    if (this.checker.isArrayType(type)) {
      const [element] = this.checker.getTypeArguments(type);
      return { kind: 'array', element: this.typeOf(element, depth + 1), readonly: false };
    }
    if (this.checker.isTupleType(type)) {
      const target = type.target;
      return {
        kind: 'tuple',
        elements: this.checker.getTypeArguments(type).map((element, index) => ({
          name: target.labeledElementDeclarations?.[index]?.name?.getText() ?? null,
          type: this.typeOf(element, depth + 1),
          optional: Boolean(target.elementFlags?.[index] & ts.ElementFlags.Optional),
          rest: Boolean(target.elementFlags?.[index] & ts.ElementFlags.Rest),
        })),
      };
    }
    if (symbol && !isUserDeclarationSymbol(symbol) && COLLECTION_TYPES.has(symbol.name)) {
      return {
        kind: 'lib',
        name: symbol.name,
        typeArguments: this.checker.getTypeArguments(type).map((argument) => this.typeOf(argument, depth + 1)),
      };
    }
    if (this.checker.getSignaturesOfType(type, ts.SignatureKind.Call).length) {
      return { kind: 'unsupported', construct: 'function_type', text: this.checker.typeToString(type) };
    }

    const properties = this.checker.getPropertiesOfType(type).map((property) => {
      const declarationNode = property.declarations?.[0];
      const optional = Boolean(property.flags & ts.SymbolFlags.Optional);
      const propertyType = this.checker.getTypeOfSymbol(property);
      return {
        name: property.name,
        optional,
        readonly: Boolean(declarationNode && hasModifier(declarationNode, ts.SyntaxKind.ReadonlyKeyword)),
        // An optional property's type carries the implicit `| undefined` under `strict`; the
        // question mark already says so, so it is not repeated as a union member.
        type: this.typeOf(propertyType, depth + 1, optional),
        doc: declarationNode ? this.documentation(declarationNode) : null,
        deprecated: declarationNode ? this.deprecated(declarationNode) : false,
        line: declarationNode && isUserDeclaration(declarationNode) ? lineOf(declarationNode) : null,
      };
    });
    const indexSignatures = this.checker.getIndexInfosOfType(type).map((info) => ({
      keyName: 'key',
      keyType: this.typeOf(info.keyType, depth + 1),
      valueType: this.typeOf(info.type, depth + 1),
      readonly: Boolean(info.isReadonly),
    }));
    return { kind: 'object', properties, indexSignatures, unsupported: [] };
  }

  // --- declarations -----------------------------------------------------------------------

  /** Serialize one top-level interface, type alias or enum declaration. */
  declaration(node, exportedIds) {
    const id = declarationId(node);
    const base = {
      id,
      name: node.name.text,
      module: moduleOf(node),
      line: lineOf(node),
      exported: exportedIds.has(id),
      doc: this.documentation(node),
      deprecated: this.deprecated(node),
      typeParameters: (node.typeParameters ?? []).map((parameter) => ({
        name: parameter.name.text,
        default: parameter.default ? this.typeNode(parameter.default) : null,
      })),
      mergedDeclarations: this.mergedCount(node),
    };
    if (ts.isInterfaceDeclaration(node)) {
      const heritage = (node.heritageClauses ?? [])
        .filter((clause) => clause.token === ts.SyntaxKind.ExtendsKeyword)
        .flatMap((clause) => clause.types)
        .map((expression) => this.heritage(expression));
      return { ...base, kind: 'interface', extends: heritage, ...this.members(node.members) };
    }
    if (ts.isTypeAliasDeclaration(node)) {
      return { ...base, kind: 'alias', type: this.typeNode(node.type) };
    }
    return {
      ...base,
      kind: 'enum',
      const: hasModifier(node, ts.SyntaxKind.ConstKeyword),
      members: node.members.map((member) => ({
        name: propertyNameText(member.name) ?? member.name.getText(),
        value: this.checker.getConstantValue(member) ?? null,
        doc: this.documentation(member),
        deprecated: this.deprecated(member),
      })),
    };
  }

  /** An `extends` clause entry, resolved like any other reference. */
  heritage(expression) {
    const name = expression.expression.getText();
    const typeArguments = (expression.typeArguments ?? []).map((argument) => this.typeNode(argument));
    const symbol = ts.isIdentifier(expression.expression) ? this.resolveSymbol(expression.expression) : null;
    if (!symbol) {
      return { kind: 'unresolved', name };
    }
    const declaration = symbol.declarations[0];
    if (isUserDeclaration(declaration) && isTypeDeclaration(declaration)) {
      return { kind: 'ref', target: declarationId(declaration), name: symbol.name, typeArguments };
    }
    return { kind: 'unsupported', construct: 'lib_type', text: expression.getText().slice(0, 200) };
  }

  /** How many declarations share this one's symbol (2+ is declaration merging). */
  mergedCount(node) {
    const symbol = this.checker.getSymbolAtLocation(node.name);
    return symbol?.declarations?.filter((declaration) => isTypeDeclaration(declaration) || ts.isModuleDeclaration(declaration)).length ?? 1;
  }
}

/** Whether a symbol is declared in one of the request's own modules. */
function isUserDeclarationSymbol(symbol) {
  return Boolean(symbol.declarations?.length && isUserDeclaration(symbol.declarations[0]));
}

/** Map one compiler diagnostic onto the wrapper's stable, JSON-friendly shape. */
function mapDiagnostic(diagnostic) {
  const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n');
  if (!diagnostic.file) {
    return { file: null, code: diagnostic.code, message, line: null, column: null, atEnd: false };
  }
  const { line, character } = diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start ?? 0);
  const contentEnd = diagnostic.file.text.trimEnd().length;
  return {
    file: diagnostic.file.fileName.slice(ROOT_DIR.length),
    code: diagnostic.code,
    message,
    line: line + 1,
    column: character + 1,
    // A syntax error at (or past) the last real character means the text stopped while a
    // construct was still open — the signal that separates a cut-short upload from a typo.
    atEnd: (diagnostic.start ?? 0) >= contentEnd,
  };
}

/** Every module specifier a file imports or re-exports from, and whether it resolved. */
function importsOf(sourceFile, options, host) {
  const out = [];
  for (const statement of sourceFile.statements) {
    const specifier =
      (ts.isImportDeclaration(statement) || ts.isExportDeclaration(statement)) && statement.moduleSpecifier
        ? statement.moduleSpecifier.text
        : null;
    if (specifier === null) {
      continue;
    }
    const { resolvedModule } = ts.resolveModuleName(specifier, sourceFile.fileName, options, host);
    out.push({
      file: sourceFile.fileName.slice(ROOT_DIR.length),
      module: specifier,
      resolved: Boolean(resolvedModule?.resolvedFileName?.startsWith(ROOT_DIR)),
    });
  }
  return out;
}

/** Run the extraction for one request and return the response object. */
function extract(request) {
  const files = request.files ?? {};
  const names = Object.keys(files).sort();
  const root = request.root && names.includes(request.root) ? request.root : names[0];
  const options = {
    target: ts.ScriptTarget.ES2022,
    lib: ['lib.es2022.d.ts'],
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    strict: true,
    noEmit: true,
    skipLibCheck: true,
    types: [],
    allowJs: false,
    isolatedModules: false,
  };
  const host = createHost(files, options);
  const program = ts.createProgram({ rootNames: names.map((name) => ROOT_DIR + name), options, host });
  const sourceFiles = names.map((name) => program.getSourceFile(ROOT_DIR + name)).filter(Boolean);

  const diagnostics = sourceFiles.flatMap((sourceFile) => program.getSyntacticDiagnostics(sourceFile)).map(mapDiagnostic);
  const response = {
    ok: diagnostics.length === 0,
    typescriptVersion: ts.version,
    root,
    files: names,
    imports: sourceFiles.flatMap((sourceFile) => importsOf(sourceFile, options, host)),
    declarations: [],
    diagnostics,
  };
  if (!response.ok) {
    return response;
  }

  const extractor = new Extractor(program);
  const checker = extractor.checker;

  // What the root module exports — its own declarations and everything it re-exports.
  const exportedIds = new Set();
  const rootFile = program.getSourceFile(ROOT_DIR + root);
  const moduleSymbol = rootFile && checker.getSymbolAtLocation(rootFile);
  for (const exported of moduleSymbol ? checker.getExportsOfModule(moduleSymbol) : []) {
    const symbol = exported.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(exported) : exported;
    for (const declaration of symbol.declarations ?? []) {
      if (isTypeDeclaration(declaration) && isUserDeclaration(declaration)) {
        exportedIds.add(declarationId(declaration));
      }
    }
  }

  // Every top-level type declaration in every module, so a non-exported helper an exported
  // type refers to is still describable. A merged interface is reported once, by its first
  // declaration, with the count that marks it as merged.
  const seen = new Set();
  for (const sourceFile of sourceFiles) {
    for (const statement of sourceFile.statements) {
      if (!isTypeDeclaration(statement)) {
        continue;
      }
      const id = declarationId(statement);
      if (seen.has(id)) {
        continue;
      }
      seen.add(id);
      response.declarations.push(extractor.declaration(statement, exportedIds));
    }
  }
  return response;
}

async function main() {
  if (process.argv.slice(2).includes('--version')) {
    printVersionAndExit();
    return;
  }
  const raw = await readStdin();
  let request;
  try {
    request = JSON.parse(raw);
  } catch (err) {
    process.stderr.write(`typescript-types-extract: request is not JSON: ${err.message}\n`);
    process.exit(2);
  }
  if (!request || typeof request !== 'object' || typeof request.files !== 'object' || !request.files) {
    process.stderr.write('typescript-types-extract: request must be {"files": {...}, "root": "..."}\n');
    process.exit(2);
  }
  process.stdout.write(JSON.stringify(extract(request)));
}

main().catch((err) => {
  process.stderr.write(`typescript-types-extract wrapper failed: ${err && err.stack ? err.stack : err}\n`);
  process.exit(1);
});

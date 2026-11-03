---
title: "Import XML-RPC method descriptions"
description: "Catalog XML-RPC method calls, responses and faults, with lint and diff rules."
sidebar_position: 23.2
tags: [import, xmlrpc, xml-rpc, rpc, legacy, lint, migrate]
---

**XML-RPC** is the 1998 remote-procedure-call protocol under WordPress, MetaWeblog, Bugzilla and
a long tail of in-house services: a `<methodCall>` names a method and carries positional, typed
`<params>`; a `<methodResponse>` carries one value or a `<fault>`. There is no schema language,
so the description of a method is a call and its reply. The **XML-RPC** importer (`xmlrpc`) reads
such a document into the [Catalog](./catalog.mdx) so the method can be searched, versioned,
diffed and linted like any other catalog item, and records how it would be rewritten as JSON-RPC.

## What you can import

A `methodCall`, a `methodResponse` or a fault:

```xml
<?xml version="1.0"?>
<methodCall>
  <methodName>inventory.reserveStock</methodName>
  <params>
    <param><value><string>WIDGET-001</string></value></param>
    <param><value><int>5</int></value></param>
    <param><value><struct>
      <member><name>customerId</name><value><string>c-7781</string></value></member>
      <member><name>priority</name><value><boolean>1</boolean></value></member>
    </struct></value></param>
  </params>
</methodCall>
```

Every XML-RPC value is read — `int` / `i4` / `i8`, `boolean`, `double`, `string`,
`dateTime.iso8601`, `base64`, `struct`, `array` and the `<nil/>` extension — and a
`system.multicall` keeps its boxed calls.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the document — try
   `apiome-ui/examples/xml-rpc/01-method-call.xml` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: XML-RPC** (`xmlrpc`) and routes it to
   the Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the document to the import endpoints with the source kind `xmlrpc`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import xmlrpc ./01-method-call.xml
```

The six examples in `apiome-ui/examples/xml-rpc/` cover a call and its response, a minimal call,
a `system.multicall`, a response using every value type, and a WordPress `wp.getPost` call.

## What Apiome reads

| In the document | Becomes |
| --- | --- |
| The `methodName` | A **service** and one **operation** named after it (`fault` for a fault), with the document's kind recorded (`xmlrpc_kind`) and, for a fault, its code and string |
| The `<params>` of a call | The operation's **request**, with each param by position: its JSON schema and sample (`xmlrpc_params`) |
| The `<param>` of a response | The operation's **response**, with the value's schema and sample (`xmlrpc_result_schema`, `xmlrpc_sample`) |
| Each `<struct>` | A **record type** named after the method and its position (`InventoryReserveStockParam3`), one field per member, the members' sample values kept (`xmlrpc_samples`) |
| Each `<array>` | A list of its first element's type; an empty array is a list of strings |
| The whole document | A **migrate-to-JSON-RPC note** (`xmlrpc_migration`): the JSON-RPC 2.0 request or response the document becomes and each value kind's JSON type — see below |

### The migrate note

XML-RPC's natural successor is JSON-RPC 2.0 described by [OpenRPC](./openrpc-import.md): the
same positional params, a struct as an object, a fault as a JSON-RPC error. The item records that
rewrite as `xmlrpc_migration`:

| XML-RPC value | JSON |
| --- | --- |
| `int`, `i4` / `i8` | `integer` / `integer` (`int64`) |
| `boolean`, `double`, `string` | `boolean`, `number`, `string` |
| `dateTime.iso8601` | `string` (`date-time`) — state a time zone |
| `base64` | `string` (`contentEncoding: base64`) |
| `struct`, `array` | `object`, `array` |
| `<nil/>` | `null` |
| `faultCode` / `faultString` | the JSON-RPC error's `code` / `message` |

## Versions and changes

Import a newer description of the same method into the same item to add a version. Because
params are positional and required and a struct is read by member name, the comparison grades
every change with those semantics:

| Change | Severity | Rule |
| --- | --- | --- |
| The call has fewer params | Breaking: positions shift | `xmlrpc.param-removed` |
| The call has more params | Breaking: old callers send too few and the server faults | `xmlrpc.param-added` |
| A param at the same position changed type | Breaking | `xmlrpc.param-type-changed` |
| The response's value changed type | Dangerous: callers that read the old shape break | `xmlrpc.result-type-changed` |
| A struct member removed, or changed type | Breaking | `xmlrpc.member-removed`, `xmlrpc.member-type-changed` |
| A member added to a request struct | Dangerous: old callers omit it | `xmlrpc.member-added-to-call` |
| A member added to a response struct | Safe: readers ignore what they do not know | `xmlrpc.member-added-to-response` |
| Only sample values, or only the fault's code or string, changed | Safe | `xmlrpc.sample-changed`, `xmlrpc.fault-changed` |

A renamed method is another method: the comparison reports the old operation removed and the new
one added.

## Lint

The **Quality** step and the item's **Lint & score** tab add the `xmlrpc` rules on top of the
common ones:

| Rule | Severity | Flags |
| --- | --- | --- |
| [`xmlrpc.method-name-namespaced`](../build/lint-rules.md#xmlrpc-method-name-namespaced) | Info | A method name without a `.`; the convention is `object.method` |
| [`xmlrpc.system-method-known`](../build/lint-rules.md#xmlrpc-system-method-known) | Warning | A `system.` method that is not `listMethods`, `methodSignature`, `methodHelp`, `multicall` or `getCapabilities` |
| [`xmlrpc.response-has-value`](../build/lint-rules.md#xmlrpc-response-has-value) | Warning | A `methodResponse` with no `<param>` |
| [`xmlrpc.fault-described`](../build/lint-rules.md#xmlrpc-fault-described) | Warning | A fault whose `faultCode` is missing or `0`, or whose `faultString` is empty |
| [`xmlrpc.nil-extension`](../build/lint-rules.md#xmlrpc-nil-extension) | Info | A `<nil/>` value, which clients without the extension cannot parse |
| [`xmlrpc.array-item-type-known`](../build/lint-rules.md#xmlrpc-array-item-type-known) | Info | An empty `<array>`, whose item type is unknown |
| [`xmlrpc.multicall-calls-wellformed`](../build/lint-rules.md#xmlrpc-multicall-calls-wellformed) | Warning | A `system.multicall` whose param is not an array of `{methodName, params}` structs |

## Export

An XML-RPC item writes back out as the same document through the **XML-RPC** target; see
[Export a spec](../ship/export-a-spec.md). To migrate it, export it to **OpenRPC** and compare the
result with the migrate note.

## When an import is refused

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SYNTAX_INVALID` | The XML is malformed or truncated | Paste the complete document |
| `INPUT_SEMANTIC_INVALID` | A `methodCall` has no `methodName` | Add it |
| `INPUT_UNSAFE_CONSTRUCT` | The document carries an external entity, DTD or XInclude | Remove it; XML-RPC needs none |
| `FORMAT_MISMATCH` | The root is neither `methodCall` nor `methodResponse` | Pick the right format |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): XML-RPC's coverage and export support
- [Import ONC RPC (XDR) definitions](./oncrpc-import.md): the other early RPC format
- [Import an OpenRPC document](./openrpc-import.md): the JSON-RPC description the migrate note targets
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
- [Legacy, mainframe and middleware formats](./legacy-and-mainframe-formats.mdx): every legacy, mainframe and middleware importer, and how they work together.

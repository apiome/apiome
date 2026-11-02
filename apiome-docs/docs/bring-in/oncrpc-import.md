---
title: "Import ONC RPC (XDR) definitions"
description: "Catalog rpcgen .x files: programs, procedures and XDR types, with lint and diff rules."
sidebar_position: 23.1
tags: [import, oncrpc, sunrpc, xdr, rpcgen, rpc, legacy, lint, migrate]
---

**ONC RPC** (Sun RPC, RFC 5531) is the remote-procedure-call layer under NFS, NIS and a
generation of in-house Unix services, and **XDR** (RFC 4506) is its wire encoding. A service is
written in the RPC language and processed by `rpcgen`: an `.x` file declares the XDR data types
(`struct`, `enum`, `typedef`, `union … switch`) and one or more `program` blocks, each with
numbered `version`s and numbered procedures. The **ONC RPC** importer (`oncrpc`) reads the `.x`
file into the [Catalog](./catalog.mdx) so the contract can be searched, versioned, diffed and
linted like any other catalog item, and records how it would be rewritten as a gRPC service.

## What you can import

An `rpcgen` `.x` file:

```c
enum kv_status { KV_OK = 0, KV_NOT_FOUND = 1, KV_ERROR = 2 };

typedef string kv_key<256>;

struct kv_entry {
    kv_key key;
    opaque value<1024>;
};

union kv_get_res switch (kv_status status) {
case KV_OK:
    kv_entry entry;
default:
    void;
};

program KV_PROG {
    version KV_VERS {
        void      KV_NULL(void) = 0;
        kv_get_res KV_GET(kv_key) = 1;
        kv_status  KV_PUT(kv_entry) = 2;
    } = 1;
} = 0x20000001;
```

Every declaration shape of RFC 4506 §6.3 is read: a bounded or unbounded variable-length
`string<N>` / `opaque<N>` / array `<N>` (or `<>`), a fixed-length array `[N]`, an optional-data
pointer `*`, and the `unsigned` qualifier. `#include` directives are not followed.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the `.x` file — try
   `apiome-ui/examples/onc-rpc/01-key-value-store.x` — or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: ONC RPC** (`oncrpc`) and routes it to
   the Catalog. A file whose `struct` declarations outrank the `program` block may detect as
   FlatBuffers; pick **ONC RPC** from the format list.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the file to the import endpoints with the source kind `oncrpc`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import oncrpc ./01-key-value-store.x
```

The six examples in `apiome-ui/examples/onc-rpc/` cover a key/value store, a file-stat service,
a composed inventory, a two-version job queue, a portmapper-style program and a metrics collector.

## What Apiome reads

| In the file | Becomes |
| --- | --- |
| Each `program` | A **service** named after it, with its number recorded (`oncrpc_program_number`) and its versions' numbers (`oncrpc_versions`) |
| Each procedure of each `version` | An **operation** with the procedure's number, version and argument / result types (`oncrpc_procedure_number`, `oncrpc_version_number`, `oncrpc_arg_type`, `oncrpc_return_type`) |
| Each `struct` | A **record type**; each field keeps its declared XDR type (`oncrpc_type_expr`), a bound becomes a constraint (`max_length` for `string<N>` / `opaque<N>`, `max_items` for an array `<N>`, `min_items` = `max_items` for `[N]`), a pointer makes the field nullable |
| Each `union … switch` | A **union type** with its discriminant and arms recorded (`oncrpc_switch_type`, `oncrpc_switch_field`, `oncrpc_union_cases`) |
| Each `enum` and `typedef` | An **enum type**; a typedef is resolved into the fields that use it and listed under `oncrpc_typedefs` |
| The whole file | A **migrate-to-gRPC note** (`oncrpc_migration`): each type as the proto3 construct it becomes, each procedure as its `rpc` line, and what the rewrite loses — see below |

### The migrate note

ONC RPC's natural successor is gRPC: a program version becomes a proto3 `service`, a procedure an
`rpc`, a struct a `message`, a union a `oneof`, an enum an enum. The item records that rewrite as
`oncrpc_migration`, so a migration starts from a table rather than from the `.x` file:

| XDR | proto3 |
| --- | --- |
| `int`, `unsigned int`, `short`, `long` | `int32`, `uint32` |
| `hyper`, `unsigned hyper` | `int64`, `uint64` |
| `float`, `double`, `quadruple` | `float`, `double`, `double` |
| `bool`, `string`, `opaque` | `bool`, `string`, `bytes` |
| `type name<N>` / `type name[N]` | `repeated type` |
| `type *name` | `optional type` |
| `union … switch` | `message { oneof … }` |
| `void` | `google.protobuf.Empty` |

The caveats the note states: program, version and procedure **numbers** have no proto3
counterpart (gRPC routes by name), a `string<N>` bound is not enforced by proto3, and a
fixed-length array becomes `repeated` with no length guarantee.

## Versions and changes

Import a newer `.x` file into the same item to add a version. Because ONC RPC dispatches by
number and XDR encodes positionally, the comparison grades every change with those semantics:

| Change | Severity | Rule |
| --- | --- | --- |
| The program's number changed | Breaking: rpcbind routes old callers to nothing | `oncrpc.program-renumbered` |
| A version's number changed, or a version removed | Breaking | `oncrpc.version-renumbered`, `oncrpc.version-removed` |
| A version added | Safe | `oncrpc.version-added` |
| A procedure's number changed | Breaking: the wire carries the number | `oncrpc.procedure-renumbered` |
| A procedure's argument or result type changed | Breaking | `oncrpc.procedure-signature-changed` |
| A procedure removed / added | Breaking / Safe | `oncrpc.procedure-removed`, `oncrpc.procedure-added` |
| A struct field added, removed or moved | Breaking: XDR is positional and carries no tags | `oncrpc.field-added`, `oncrpc.field-removed`, `oncrpc.field-reordered` |
| A field's XDR type changed | Breaking | `oncrpc.field-type-changed` |
| A `<N>` bound shrank | Breaking: old senders overflow it | `oncrpc.bound-narrowed` |
| A `<N>` bound grew or was dropped | Dangerous: old receivers reject the longer values | `oncrpc.bound-widened` |
| A union's discriminant changed, or an arm removed | Breaking | `oncrpc.union-discriminant-changed`, `oncrpc.union-arm-removed` |
| A union arm added | Dangerous: old receivers without a `default` cannot decode it | `oncrpc.union-arm-added` |
| An enumerator removed or renumbered | Breaking | `oncrpc.enum-value-removed`, `oncrpc.enum-value-renumbered` |
| An enumerator added | Safe | `oncrpc.enum-value-added` |

## Lint

The **Quality** step and the item's **Lint & score** tab add the `oncrpc` rules on top of the
common ones:

| Rule | Severity | Flags |
| --- | --- | --- |
| [`oncrpc.program-number-reserved`](../build/lint-rules.md#oncrpc-program-number-reserved) | Warning | A program number at or above `0x60000000`, the block RFC 5531 reserves |
| [`oncrpc.program-number-assigned`](../build/lint-rules.md#oncrpc-program-number-assigned) | Info | A program number below `0x20000000`, the IANA-assigned block; a site-defined program belongs in `0x20000000`–`0x3FFFFFFF` |
| [`oncrpc.version-numbers-unique`](../build/lint-rules.md#oncrpc-version-numbers-unique) | Error | Two versions of a program with the same number |
| [`oncrpc.procedure-numbers-unique`](../build/lint-rules.md#oncrpc-procedure-numbers-unique) | Error | Two procedures of a version with the same number |
| [`oncrpc.procedure-names-unique`](../build/lint-rules.md#oncrpc-procedure-names-unique) | Error | Two procedures of a version with the same name |
| [`oncrpc.null-procedure-declared`](../build/lint-rules.md#oncrpc-null-procedure-declared) | Info | A version without procedure `0`, the null procedure `rpcinfo` and liveness checks call |
| [`oncrpc.null-procedure-void`](../build/lint-rules.md#oncrpc-null-procedure-void) | Warning | A procedure `0` that takes or returns something |
| [`oncrpc.variable-length-bounded`](../build/lint-rules.md#oncrpc-variable-length-bounded) | Info | An unbounded `string<>`, `opaque<>` or array `<>` |
| [`oncrpc.type-resolves`](../build/lint-rules.md#oncrpc-type-resolves) | Error | A field type that is neither an XDR base type nor a type the file declares |
| [`oncrpc.union-has-default`](../build/lint-rules.md#oncrpc-union-has-default) | Info | A `union … switch` without a `default` arm |
| [`oncrpc.enum-values-unique`](../build/lint-rules.md#oncrpc-enum-values-unique) | Error | Two enumerators with the same number |

## Export

An ONC RPC item writes back out as an `rpcgen` `.x` file through the **ONC RPC** target; see
[Export a spec](../ship/export-a-spec.md). To migrate it, export it to **Protocol Buffers** and
compare the result with the migrate note.

## When an import is refused

| Code | Why | What to do |
| --- | --- | --- |
| `INPUT_SYNTAX_INVALID` | A `program`, `version`, `struct` or `union` block is unclosed, or a version has no `= N;` number | Close the block and number every version and program |
| `INPUT_SEMANTIC_INVALID` | The file declares no `program` and no XDR type | Add the declarations |
| `FORMAT_MISMATCH` | The file is not RPC language (a `.proto`, a FlatBuffers schema) | Pick the right format |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): ONC RPC's coverage and export support
- [Import XML-RPC method descriptions](./xmlrpc-import.md): the other early RPC format
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale

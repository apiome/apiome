---
title: "Import ASN.1 modules"
description: "Catalog ASN.1 modules with tags, constraints and extensions, plus lint and encoding-aware diffs."
sidebar_position: 44.6
tags: [import, asn1, x509, telecom, pki, ber, der, per, lint]
---

**ASN.1** (Abstract Syntax Notation One, ITU-T X.680) is the schema language behind every X.509
certificate, 4G / 5G signalling, SNMP, LDAP and much of the PKI and telecom stack. A module
declares types (`SEQUENCE`, `SET`, `CHOICE`, `ENUMERATED`, `SEQUENCE OF`…) and the **tags** and
**constraints** their encodings (BER, DER, PER…) depend on. The **ASN.1** importer (`asn1`) reads a
module into the [Catalog](./catalog.mdx), so its types can be searched, versioned, diffed and
linted like any other catalog item.

## What you can import

One ASN.1 module per file:

```asn1
Subscriber-Provisioning DEFINITIONS IMPLICIT TAGS ::= BEGIN

  ServiceClass ::= ENUMERATED { basic(0), premium(1), ... }

  Identity ::= CHOICE {
    imsi    [0] OCTET STRING (SIZE (3..8)),
    msisdn  [1] NumericString (SIZE (1..15))
  }

  Subscriber ::= SEQUENCE {
    identity      [0] Identity,
    serviceClass  [1] ServiceClass DEFAULT basic,
    maxSessions   [2] INTEGER (1..16) DEFAULT 4,
    ...,
    roaming       [5] BOOLEAN OPTIONAL
  }

END
```

Apiome reads:
- the module's tagging default (`EXPLICIT`, `IMPLICIT` or `AUTOMATIC TAGS`), `EXTENSIBILITY IMPLIED`
  and its `IMPORTS`;
- every type assignment, including `Version ::= INTEGER { v1(0) }`, `Names ::= SEQUENCE OF Name`
  and `Alias ::= Other` (top-level typedefs like these used to make the import fail);
- tags (`[APPLICATION 3] IMPLICIT`), value ranges (`(0..255)`), `SIZE` constraints, `OPTIONAL`,
  `DEFAULT`, named numbers and named bits;
- the extension marker `...`, and every component, alternative or enumeration item after it
  (`[[ … ]]` groups included);
- an inline `SEQUENCE`, `SET` or `CHOICE` component, as its own type.

Value assignments (`id-x OBJECT IDENTIFIER ::= { … }`), information object classes and
parameterized types are not modelled. A file may hold one module.

## Import it

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File** and drop the `.asn1` or `.asn` file (try
   `apiome-ui/examples/asn1/06-x509-certificate-shape.asn1`), or choose **Paste** and paste it.
3. On **Detect & route**, Apiome reports **Auto-detected: ASN.1** (`asn1`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the file to the import endpoints with the source kind `asn1`; see
[Import sources](../reference/rest/import-sources.md). From the CLI:

```bash
apiome import asn1 ./06-x509-certificate-shape.asn1
```

The seven examples in `apiome-ui/examples/asn1/` cover:
- a person record and an identifier CHOICE;
- a minimal module, and a module that imports types from another;
- a module with every tag and constraint form;
- the shape of an X.509 certificate;
- top-level scalar and list typedefs.

## What Apiome reads

| In the module | Becomes |
| --- | --- |
| `SEQUENCE` / `SET` | A **record type**: components are fields in declaration order (`asn1_kind` is `SET` for a SET), `OPTIONAL` makes a field optional and `DEFAULT` gives its default |
| `CHOICE` | A **union type**. Each alternative's name, type, tag and constraints are kept in `asn1_choice_members`. |
| `ENUMERATED` | An **enum type**, with each item's number; an inline one becomes a `<Type><Component>` enum |
| An inline `SEQUENCE` / `SET` / `CHOICE` component | Its own `<Type><Component>` type |
| `Name ::= INTEGER`, `Name ::= SEQUENCE OF X`, `Name ::= Other` | An **alias** of the built-in, the list or the other type |
| A value range / `SIZE` | `minimum` / `maximum`, `min_length` / `max_length` (strings), or `min_items` / `max_items` (lists) |
| A tag | `asn1_tag`: class, number and the kind it resolves to (written, else the module default; a CHOICE's tag is always explicit) |
| `...` and what follows it | `asn1_extensible` on the type, `asn1_extension` on each extension addition |
| A built-in type (`IA5String`, `OBJECT IDENTIFIER`, `BIT STRING`…) | Kept in `asn1_type`, so an export writes the same type back |

## Versions and changes

Import a newer module into the same item to add a version. The comparison grades each change by
how an old peer decodes a new value:
- BER and DER decoders find components by **tag**.
- PER decoders find them by **position and constraints**.
- Only an **extension marker** lets a decoder skip something new.

| Change | Severity | Rule |
| --- | --- | --- |
| A component added after `...` | Safe: old decoders skip it | `asn1.component-added-as-extension` |
| An OPTIONAL component added to the root | Dangerous: strict and PER decoders reject it | `asn1.component-added-optional` |
| A mandatory component added, or a component removed | Breaking | `asn1.component-added-required`, `asn1.component-removed` |
| A component's type, tag or DEFAULT changed | Breaking | `asn1.component-type-changed`, `asn1.tag-changed`, `asn1.default-changed` |
| A component made mandatory / made OPTIONAL | Breaking / Dangerous | `asn1.component-made-required`, `asn1.component-made-optional` |
| A component moved into or out of the extension additions | Breaking | `asn1.extension-moved` |
| SEQUENCE components swapped | Breaking: decoded in order | `asn1.component-reordered` |
| A component moved only because another was added or removed | Safe | `asn1.component-shifted` |
| SET components moved | Safe: a SET is decoded by tag | `asn1.set-component-moved` |
| A value range or `SIZE` narrowed / widened | Breaking / Dangerous | `asn1.constraint-narrowed`, `asn1.constraint-widened` |
| An ENUMERATED item removed or renumbered | Breaking | `asn1.enum-item-removed`, `asn1.enum-item-renumbered` |
| An ENUMERATED item added after `...` / to the root | Safe / Dangerous | `asn1.enum-item-added-as-extension`, `asn1.enum-item-added` |
| A CHOICE alternative removed or re-typed | Breaking | `asn1.alternative-removed`, `asn1.alternative-type-changed` |
| A CHOICE alternative added after `...` / to the root | Safe / Dangerous | `asn1.alternative-added-as-extension`, `asn1.alternative-added` |
| The extension marker removed / added | Breaking / Dangerous | `asn1.extension-marker-removed`, `asn1.extension-marker-added` |
| A SEQUENCE became a SET, or back | Breaking: UNIVERSAL 16 ↔ 17 | `asn1.kind-changed` |
| A type assignment refers to another type | Breaking | `asn1.alias-target-changed` |

A removed type is breaking, and an added one is safe.

## Lint

The **Quality** step and the item's **Lint & score** tab add the `asn1` rules on top of the
common ones. A component's tag is the one written on it, else the UNIVERSAL tag of its type. In an
`AUTOMATIC TAGS` module, a type whose components carry no tag is tagged automatically and is never
ambiguous.

| Rule | Severity | Flags |
| --- | --- | --- |
| [`asn1.type-resolves`](../build/lint-rules.md#asn1-type-resolves) | Error | A reference that is not built in, not assigned in the module and not imported |
| [`asn1.choice-tags-distinct`](../build/lint-rules.md#asn1-choice-tags-distinct) | Error | Two CHOICE alternatives with the same tag |
| [`asn1.set-tags-distinct`](../build/lint-rules.md#asn1-set-tags-distinct) | Error | Two SET components with the same tag |
| [`asn1.sequence-tags-unambiguous`](../build/lint-rules.md#asn1-sequence-tags-unambiguous) | Error | An OPTIONAL / DEFAULT component that shares its tag with a component that may follow it |
| [`asn1.default-valid`](../build/lint-rules.md#asn1-default-valid) | Warning | A DEFAULT outside the value range, or naming an item the type does not declare |
| [`asn1.any-deprecated`](../build/lint-rules.md#asn1-any-deprecated) | Warning | `ANY`, removed from ASN.1 in 1994 |
| [`asn1.legacy-string-type`](../build/lint-rules.md#asn1-legacy-string-type) | Info | `TeletexString`, `T61String`, `VideotexString`, `GraphicString`, `GeneralString` or `UniversalString` (RFC 5280 asks for `UTF8String`) |
| [`asn1.extension-marker`](../build/lint-rules.md#asn1-extension-marker) | Info | A SEQUENCE, SET, CHOICE or ENUMERATED without `...` |

## Export

An ASN.1 item writes back out as an ASN.1 module through the **ASN.1** target; see
[Export a spec](../ship/export-a-spec.md). The export keeps the module's:
- tags, each with its kind written out (`[0] IMPLICIT`), so the module's tagging default cannot
  change their meaning;
- extension markers;
- `SET`s, named numbers and DEFAULT values;
- declared character-string types (`IA5String` stays `IA5String`);
- constraints on CHOICE alternatives.

## When an import is refused

| Message | Why | What to do |
| --- | --- | --- |
| `Malformed ASN.1 module: Invalid ASN.1 syntax at line …` | A brace is not closed, or the module is cut off | Fix the module at the line and column given |
| `ASN.1 module … defines no types` | The module has no type assignment | Add the types |
| `ASN.1 import supports a single module per document` | The file holds several modules | Import each module on its own |
| `Content does not appear to be an ASN.1 module` | There is no `DEFINITIONS … ::= BEGIN` header (another format, or a UTF-16 file) | Pick the right format, or save the file as UTF-8 |

## Related

- [Import a specification](./import-a-spec.md): the import paths every format shares
- [Supported formats](./supported-formats.md): ASN.1's coverage and export support
- [Import CORBA IDL (OMG IDL) definitions](./corba-idl-import.md): another long-lived interface language
- [Built-in lint rules](../build/lint-rules.md): every rule with its rationale
- [Legacy, mainframe and middleware formats](./legacy-and-mainframe-formats.mdx): every legacy, mainframe and middleware importer, and how they work together.

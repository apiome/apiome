---
title: "Link z/OS Connect to its copybooks"
description: "Keep a z/OS Connect API, its copybooks and its OpenAPI linked in the catalog."
sidebar_position: 47
tags: [import, mainframe, zos-connect, cobol, copybook, openapi, catalog]
---

IBM z/OS Connect lets a CICS or IMS program call a REST API, or exposes one as a REST API. Its
**descriptor** binds each REST operation to the COBOL structures the program passes: a request
structure and a response structure, each an 01-level record in a copybook. Apiome keeps the three
sides of that binding together: the descriptor, its copybooks, and the OpenAPI document for the REST
API.

## Import the three sides

Import each file like any other catalog format, in the [import wizard](./import-wizard.mdx) or over
the REST API ([Import a specification](./import-a-spec.md)):

1. **The z/OS Connect descriptor** (`.zosconnect.json` or `.json`), the API requester or API
   provider JSON. Each operation names its `requestStructure` and `responseStructure`.
2. **The copybooks** (`.cpy`). A copybook can declare several 01-level records, such as a request
   and its response, and every one of them counts.
3. **The OpenAPI document** for the REST API.

Each import records what the binding needs: the descriptor its operations and structures, each
copybook every 01-level record name it declares.

## Link them

On the descriptor's catalog item, **click “Suggest links”** in **Related artifacts**. Apiome suggests:

- each copybook that declares a structure the descriptor binds ("binds COBOL structure(s)
  GET-STOCK-REQUEST, GET-STOCK-RESPONSE");
- the OpenAPI document whose title is the descriptor's target API, and that defines its operations
  ("z/OS Connect target API; 2 shared operation(s)").

**Click “Link”** on each suggestion you confirm. Suggestions are never linked for you. A copybook's
own item suggests its descriptor the same way.

## Browse the binding

A z/OS Connect descriptor's item shows a **z/OS Connect binding** panel under its header. It has one
row per operation:

| Column | Shows |
| --- | --- |
| **Operation** | The method and path, and the CICS / IMS program when the descriptor names one |
| **Request structure** / **Response structure** | The COBOL record, and the copybook items that declare it |
| **OpenAPI** | The items whose OpenAPI defines the operation |

<Screenshot id="catalog-zosconnect-binding" alt="The z/OS Connect binding panel: two operations, each with its request and response COBOL structures, the GETSTOCK copybook marked Linked, and the Inventory API OpenAPI marked Not linked" />

An item marked **Linked** is linked to the descriptor. **Not linked** means it matches but has not
been confirmed: link it from **Related artifacts**. **No copybook in the catalog** means no imported
copybook declares that record yet.

Over the REST API, `GET /v1/identity/{tenant}/projects/{id}/zosconnect-binding` returns the same
binding.

## See a binding change

The binding is part of the descriptor's model, so importing a new version of the descriptor and
comparing versions shows an operation that now passes a different structure: the operation is
**modified**, and the old and new structures are removed and added.

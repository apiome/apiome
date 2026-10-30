---
title: "Import FHIR APIs and profiles"
description: "Catalog a FHIR server's CapabilityStatement and its R4, R5 or R6 profiles."
sidebar_position: 48
tags: [import, fhir, hl7, healthcare]
---

**HL7 FHIR** is the REST standard for healthcare APIs. Every FHIR server describes itself at
`<base>/metadata` with a **CapabilityStatement**: the resources it serves, what you can do with each,
and the **profiles** (StructureDefinitions) they conform to. Apiome imports both into the
[Catalog](./catalog.mdx), in FHIR **R4**, **R5** and **R6** (the R6 ballot), and records which
release each one targets.

## What you can import

| You have | What Apiome makes of it |
| --- | --- |
| A server's CapabilityStatement (`resourceType: CapabilityStatement`, the `/metadata` response) | The server's API: a service per resource, an operation per interaction it declares |
| A profile (`resourceType: StructureDefinition`) | A resource type with the profile's elements as fields |
| A resource instance (a `Patient`, an `Observation` …) | A resource type inferred from the instance |
| A `Bundle` of StructureDefinitions | One type per resource in the bundle |

## Import a file

1. **Go to Bring in → Catalog** and **click "Import to catalog"** (see the
   [import wizard](./import-wizard.mdx#import-to-catalog)).
2. On **Source**, choose **File Upload** and drop the document — try
   `apiome-ui/examples/fhir/07-capability-statement-r5.json` — or choose **URL Import**, enter a
   server's `/metadata` address in **Document URL** (for example
   `https://fhir.example.com/r4/metadata`) and **click "Fetch and detect"**.
3. On **Detect & route**, Apiome reports **Auto-detected: FHIR** (`fhir`) and routes it to the
   Catalog.
4. On **Quality**, review the lint findings and **click "Import"**.

Over the API, send the document to the import endpoints with the source kind `fhir`; see
[Import sources](../reference/rest/import-sources.md).

## What Apiome reads from a CapabilityStatement

Only what the server **declares**. A resource that allows `read` and `search-type` gets those two
operations and nothing else.

| Interaction | Operation |
| --- | --- |
| `read` | `GET /{type}/{id}` |
| `vread` | `GET /{type}/{id}/_history/{vid}` |
| `search-type` | `GET /{type}`, with a query parameter for each `searchParam` |
| `create` | `POST /{type}` |
| `update` | `PUT /{type}/{id}` |
| `patch` | `PATCH /{type}/{id}` |
| `delete` | `DELETE /{type}/{id}` |
| `history-instance` / `history-type` | `GET /{type}/{id}/_history` / `GET /{type}/_history` |
| An `operation` on a resource | `POST /{type}/${name}` |
| An `operation` on the server | `POST /${name}`, under a **system** service |

Search parameters of type `number` are numbers; every other type (`token`, `reference`, `date`,
`quantity` …) is sent as a string. Each resource's type names the profile it conforms to; import the
profile itself to see its elements. Only `server` entries in `rest` are read.

## FHIR releases

Apiome reads the `fhirVersion` a CapabilityStatement or profile declares and records its release:

| `fhirVersion` | Release |
| --- | --- |
| `4.0.x` | R4 |
| `4.3.x` | R4B |
| `5.0.x` | R5 |
| `6.0.x`, `6.0.0-ballot…` | R6 (read and labelled; nothing R6 adds beyond R5 is interpreted yet) |

The release is part of what the item's version compares. Import a profile's R4 edition, then its R5
edition, and the second import adds a version, with a change report against the first. A document
that names no `fhirVersion` is imported without a release.

## Keep a server's item fresh

A catalog item imported from a server's CapabilityStatement can re-read it on a schedule. **Open the
item**, **click the Provenance tab**, **click "Set up refresh…"** on **Live refresh**, choose **FHIR
server /metadata** in **Discover with**, and enter the server's base URL (for example
`https://fhir.example.com/r4`). Apiome reads `<base>/metadata` and adds a version when the server's
API changed. See [Keep a catalog item fresh](./catalog-refresh.mdx).

To import every profile a server declares as well, add a `registry` connector whose scope names
the `fhir-metadata` crawl, with `"includeProfiles": true` — for example
`apiome connectors add --kind registry --name lab-fhir --base-url https://fhir.example.com/r4 --scope '{"protocol": "fhir-metadata", "includeProfiles": true}'`
(see [`apiome connectors`](../reference/cli/connectors.md) and the
[Connectors API](../reference/rest/connectors.md)).

## Lint

The **Quality** step and the item's **Lint & score** tab add FHIR hygiene rules:

| Rule | Flags |
| --- | --- |
| `fhir.profile-status` | A profile that is `draft`, `retired` or `unknown` |
| `fhir.profile-url` | A profile with no canonical `url` |
| `fhir.profile-version` | A profile with no `fhirVersion` |
| `fhir.profile-base` | A constraint profile with no `baseDefinition` |
| `fhir.element-short` | An element with neither `short` nor `definition` |
| `fhir.capability-version` | A CapabilityStatement with no `fhirVersion` |
| `fhir.capability-profile` | A resource the server offers with no `profile` or `supportedProfile` |
| `fhir.capability-search` | A resource that allows search but declares no `searchParam` |

## Where next

- [Supported formats](./supported-formats.md): FHIR's input kinds and versions
- [Keep a catalog item fresh](./catalog-refresh.mdx): live refresh and drift alerts
- [Export a spec](../ship/export-a-spec.md): write a catalog item back out as FHIR

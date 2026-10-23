---
title: "Import an Apigee proxy bundle"
description: "Import an Apigee proxy bundle: flows, targets, policies and conditions."
sidebar_position: 10
tags: [import, apigee, gateway]
---

An **Apigee proxy bundle** is a zip of `apiproxy/` XML files: the proxy's endpoints, its target
endpoints, the flows and conditions that route requests, and one file per policy. Apiome reads the
bundle and records what the proxy serves and enforces.

## What you can import

| You have | Import it as |
| --- | --- |
| A proxy bundle (`.zip` with `apiproxy/<name>.xml`, `proxies/`, `targets/`, `policies/`) | One file |
| A single `ProxyEndpoint` or `TargetEndpoint` XML file | One file |
| A proxy endpoint and the shared flow it calls | One archive with both files |

## Get the bundle

Download a revision from Apigee, for example with the management API:

```bash
curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -o orders-v2.zip \
  "https://apigee.googleapis.com/v1/organizations/my-org/apis/orders-v2/revisions/7?format=bundle"
```

In the Apigee console, open the proxy, choose **Project** → **Download revision**.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises the bundle and picks the **Apigee proxy bundle** importer (`apigee`). The API lands in the
[Catalog](./catalog.mdx). To make it a Project, [convert it to OpenAPI](./convert-to-openapi.md).

## What Apiome reads

| In the bundle | Becomes |
| --- | --- |
| A `ProxyEndpoint` and its `HTTPProxyConnection` base path | A service; the base path prefixes every route |
| A `Flow` whose condition names a path and a verb | An **operation**. `MatchesPath "/orders/*"` becomes `/orders/{segment1}`, `**` becomes `{path}`, and a flow without a verb becomes `ANY`. |
| A `TargetEndpoint` | A **server**: its URL, or for a load balancer a URL template whose `server` variable lists the balanced servers |
| `VerifyAPIKey`, `OAuthV2` (verify access token) | The operation's **security** |
| `SpikeArrest`, `Quota` | **Rate limits** |
| An `AssignMessage` that sets `Access-Control-*` headers | **CORS** |

Policies in the `PreFlow` and `PostFlow` apply to every operation; a flow's own policies apply to its
operation. A policy that runs only under a condition keeps the condition. A `FlowCallout` into a
shared flow brings in the shared flow's steps when the archive carries it.

## Conditions that are not a path and a verb

A condition is a boolean expression, so not every one can become a route. Apiome keeps each of these
as a **declared condition** instead of dropping it:

- a flow condition that tests a header, a variable or uses `or` / `not`. When part of it is a path and a
  verb, the operation is still created and the rest is attached to it;
- a flow with **no** condition (it runs for every request);
- a route rule whose condition is not a path and verb;
- a route rule with **no target endpoint**: requests that match it never reach a backend.

Declared conditions, the ordered route rules, fault rules, policies Apiome does not interpret (kept
verbatim) and steps whose policy file is missing are all listed in the import's coverage ledger.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | The bundle has no `ProxyEndpoint`, so it serves no route. |
| `INPUT_REFERENCE_UNRESOLVED` | A route rule names a target endpoint the bundle does not contain. A single proxy endpoint file is not checked, since its targets live elsewhere. |
| `INPUT_ARCHIVE_INVALID` | The zip is cut off or unsafe. |
| `FORMAT_MISMATCH` | The file is not an Apigee bundle or endpoint file. |
| `INPUT_MALFORMED`, `INPUT_TRUNCATED`, `INPUT_ENCODING_INVALID` | The XML is not well formed, is cut off, or is not UTF-8. |

## Related

- [Supported formats](./supported-formats.md): the versions this importer reads.
- [Connectors API](../reference/rest/connectors.md): sync every deployed proxy of an Apigee organization automatically.
- [Import an AWS API Gateway export](./aws-api-gateway-import.md) and
  [Import an Azure API Management API](./azure-api-management-import.md): the same idea for the other gateways.

---
title: "Import an Azure API Management API"
description: "Import an APIM API with its policies: JWT, rate limits, backends and CORS."
sidebar_position: 9
tags: [import, azure, gateway]
---

An API in **Azure API Management** (APIM) has two halves: its **definition** (paths, parameters,
schemas) and a separate XML **policy** document per scope. The policies say what the gateway
actually enforces: who may call the API (JWT validation, IP filters), how often (rate limits and
quotas), which backend a request goes to and how its URL is rewritten, and which origins may call
it from a browser. None of that is in the definition. Apiome reads both halves.

## What you can import

| You have | Import it as |
| --- | --- |
| A policy document (`<policies>` with `inbound`, `backend`, `outbound` and `on-error` sections) | One file. It is read as the API's policy. |
| An **ARM template** that lists `Microsoft.ApiManagement/service/…` resources | One file. APIs, operations, API and operation policies, products, backends, named values and version sets are all read. |
| The **OpenAPI definition** APIM exports, with its policy files | One archive (`.zip` or `.tar.gz`) with the definition and the policy files. |

### Name the policy files in an archive

In an archive, the file name says which scope a policy belongs to:

| File | Scope |
| --- | --- |
| `policy.xml` or `api.policy.xml` | The API |
| `operations/{operationId}.xml` or `{operationId}.policy.xml` | One operation. The name must match the operation's `operationId` in the definition (APIM uses the operation name). |
| `products/{product}.xml` | A product |
| `global.xml` | Every API in the service |

An ARM template in the same archive adds the backends, named values and products it declares.

## Export from Azure

Export the definition as OpenAPI:

```bash
az apim api export --resource-group rg-apis --service-name contoso-apim \
  --api-id orders-api --export-format OpenApiJsonFile --file-path .
```

Then save each policy you want imported. In the Azure portal, open the API, choose **All
operations** (or one operation), open the **Policy code editor** and save its XML to a file named as
in the table above. To export a whole service as an ARM template, use the APIM DevOps resource
kit's extractor or **Export template** on the resource group.

## Import it

Import the file or archive like any other specification: in the
[import wizard](./import-wizard.mdx), with `apiome import`, or through the REST API (see
[Import a specification](./import-a-spec.md)). Apiome recognises an APIM policy, ARM template or
exported definition and picks the **Azure API Management** importer (`azure-apim`). The API lands
in the [Catalog](./catalog.mdx). To make it a Project, [convert it to OpenAPI](./convert-to-openapi.md).

An OpenAPI document with no sign of APIM (no `Ocp-Apim-Subscription-Key` scheme and no
`azure-api.net` server) is imported as plain OpenAPI, as before.

## What Apiome reads

The paths, parameters, request and response bodies and schemas import exactly as they would from
OpenAPI. An ARM template's operations are first written as the OpenAPI document APIM would export,
so they import the same way.

Policies are then combined the way APIM runs them. `<base />` stands for the parent scope's
policies (global, then product, then API, then operation), so a policy placed before `<base />`
runs before the inherited ones. Each operation records the policies that apply to it:

| Policy | Becomes |
| --- | --- |
| `validate-jwt`, `validate-azure-ad-token`, `check-header` | The operation's **security**: the token's header, OpenID configuration, audiences, issuers, required claims and scopes |
| `rate-limit`, `rate-limit-by-key`, `quota`, `quota-by-key` | **Rate limits**: calls, renewal period, bandwidth and the counter key |
| `set-backend-service`, `authentication-certificate`, `authentication-basic`, `authentication-managed-identity` | The operation's **backend** and how the gateway authenticates to it. An API-wide backend URL is also added as a server named `backend`. |
| `rewrite-uri`, `set-method`, `set-query-parameter` | The **rewrite** toward the backend |
| `cors` | **CORS**: allowed origins, methods and headers |
| `ip-filter` | The **access** posture: allowed or blocked addresses |

The definition's own facts, such as APIM's subscription key, are marked as coming from the
**definition**. The policies' facts are marked as coming from a **policy**, with the scope that
declared them. A policy inside `<choose>` or `<retry>` is marked **conditional**. Passwords and
client secrets in a policy are never stored.

## What Apiome keeps but does not interpret

Caching (`cache-lookup`, `cache-store`), `send-request`, `set-header`, `json-to-xml` and the other
policies with no place in the canonical model are kept **verbatim**. Each one is listed in the
import's coverage ledger as **partially mapped**, with its scope, section and operation.

A policy Apiome does not recognise, such as one your deployment pipeline adds, is kept and listed
the same way. Nothing is dropped silently.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_REFERENCE_UNRESOLVED` | A policy uses a named value (`{{name}}`) the input does not declare, or a `backend-id` missing from the backends the input declares. Add the `namedValues` or `backends` resources (names only for named values). |
| `INPUT_SEMANTIC_INVALID` | A `<policies>` document has none of the four sections, so it defines no policy. |
| `FORMAT_MISMATCH` | The file is not an APIM policy, ARM template or exported definition, or it is plain OpenAPI. |
| `INPUT_TRUNCATED`, `INPUT_MALFORMED`, `INPUT_ENCODING_INVALID` | The file is cut off, is not valid XML, JSON or YAML, or is not UTF-8. |

A lone policy document cannot declare backends, so a `backend-id` in it is not refused. It is
listed in the coverage ledger as unresolved.

## Related

- [Supported formats](./supported-formats.md): the shapes this importer reads.
- [Import an AWS API Gateway export](./aws-api-gateway-import.md): the same idea for Amazon API Gateway.

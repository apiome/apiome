---
title: "Import an AWS API Gateway export"
description: "Import a REST or HTTP API exported from API Gateway, extensions included."
sidebar_position: 8
tags: [import, aws, gateway]
---

An API exported from **Amazon API Gateway** is an OpenAPI document plus `x-amazon-apigateway-*`
extensions. The extensions say what the API actually does: which backend each route calls, who may
call it, what is validated and which origins may call it from a browser. A hand-written spec usually
leaves all of that out. Apiome reads both the document and its extensions.

## Export the API

Export with the extensions included. For a **REST API**:

```bash
aws apigateway get-export --rest-api-id a1b2c3d4e5 --stage-name prod \
  --export-type oas30 --parameters extensions=apigateway \
  --accepts application/yaml orders-api.yaml
```

For an **HTTP API**:

```bash
aws apigatewayv2 export-api --api-id p1q2r3s4t5 --output-type YAML \
  --specification OAS30 --include-extensions subscriptions-api.yaml
```

A Swagger 2.0 export (`--export-type swagger`) works too.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises the export by its extensions and picks the **AWS API Gateway** importer
(`aws-apigateway`). The API lands in the [Catalog](./catalog.mdx). To make it a Project,
[convert it to OpenAPI](./convert-to-openapi.md).

A document with **no** AWS extensions is imported as plain OpenAPI, as before.

If the export keeps its schemas in a separate file and reaches them with a relative `$ref`, upload
both files together as an archive. Apiome copies the referenced schemas and parameters into the
API, so the two files import as one API.

## What Apiome reads

The paths, parameters, request and response bodies and schemas import exactly as they would from
OpenAPI. On top of that, each extension maps to a part of the catalog item, labelled **declared**
because the export states it:

| Extension | Becomes |
| --- | --- |
| `x-amazon-apigateway-integration` | The operation's **backend**: Lambda proxy, HTTP proxy, AWS service, HTTP or mock, with its URI, VPC link and the stage variables it uses |
| `x-amazon-apigateway-authorizer`, `-authtype`, `-auth`, `-api-key-required` | The operation's **security**: Lambda token or request authorizers, Cognito, JWT, IAM (SigV4) and API keys |
| `x-amazon-apigateway-request-validator(s)` | The operation's **validation posture**: whether the body and the parameters are validated |
| `x-amazon-apigateway-cors`, or a mock `OPTIONS` integration that returns `Access-Control-Allow-*` headers | **CORS**: allowed origins, methods and headers |
| `x-amazon-apigateway-any-method` | An `ANY` operation on that path |

Request and response templates and parameter mappings are kept with the backend.

## What Apiome keeps but does not interpret

The resource policy, gateway responses, binary media types, endpoint configuration and the other
documented extensions have no place in the canonical model. Apiome keeps them unchanged and lists
them in the import's coverage ledger as **partially mapped**.

An extension Apiome does not recognise, such as your own `x-team-owner`, is also kept unchanged
and listed in the ledger with where it appeared. Nothing is dropped silently.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | An integration has no `type`, or a type API Gateway does not have, so its backend cannot be resolved. The message names the operation. |
| `FORMAT_MISMATCH` | You chose the AWS importer for a document with no AWS extensions. Import it as OpenAPI. |
| `INPUT_TRUNCATED`, `INPUT_MALFORMED`, `INPUT_ENCODING_INVALID` | The file is cut off, is not valid JSON or YAML, or is not UTF-8. |

## Related

- [Supported formats](./supported-formats.md): the versions this importer reads.
- [Import an Azure API Management API](./azure-api-management-import.md): the same idea for Azure.
- [Connectors](./connectors.mdx#aws-api-gateway): sync every deployed stage of an AWS account automatically.

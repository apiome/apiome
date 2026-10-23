---
title: "Export to an API gateway"
description: "Export an API as Kong, Envoy, Istio, Traefik, AWS, Azure or Apigee configuration."
sidebar_position: 2.5
tags: [export, gateway, kong, envoy, istio, traefik, aws, azure, apigee]
---

An API you governed in Apiome can be exported straight back into an API gateway's own
configuration format — the gateway it was imported from, or a different one. Every gateway
target works from the same routing view of the API (hosts, paths, methods, header and query
matches, backends and authentication), so moving an API from one gateway to another is one
export: an Apigee proxy becomes a Kong declarative config, an nginx site becomes an Envoy route
table.

## The gateway targets

Each target is a card under **REST & HTTP** in the **Export Studio**.

| Target | What you get | Re-imports as |
| --- | --- | --- |
| **Kong Declarative Config** | `kong.yaml` — services, routes and plugins for decK | `kong` |
| **Gateway API HTTPRoute** | `HTTPRoute` manifests | `gateway-api` |
| **Envoy xDS RouteConfiguration** | `route-config.yaml` — a v3 `RouteConfiguration` with a virtual host per service and a route per match | `envoy-xds` |
| **Istio VirtualService** | `virtualservice.yaml` — a `VirtualService` per service with an `http` rule per route | `istio` |
| **Traefik dynamic configuration** | `dynamic.yml` — a router per route (its `rule` rebuilt from the matches) and a load-balancer service per upstream | `traefik` |
| **AWS API Gateway** | `openapi.json` — OpenAPI 3.0 with an `x-amazon-apigateway-integration` on every operation | `aws-apigateway` |
| **Azure API Management** | `openapi.json` plus `policy.xml` and `operations/{operationId}.xml` | `azure-apim` |
| **Apigee API proxy** | an `apiproxy/` bundle — manifest, proxy endpoint, target endpoints and policies | `apigee` |

AWS API Gateway and Azure API Management are built on the OpenAPI projection, so request and
response schemas survive. The other targets are routing surfaces: they say where a request goes,
not what it carries, so schemas are declared losses.

## Export it

1. Open the API's catalog item or version and **click “Export”**.
2. In the **Export Studio**, pick the gateway's card under **REST & HTTP**.
3. Read the **fidelity report**: what is preserved, approximated and dropped. Acknowledge a lossy
   conversion to continue.
4. **Click “Export”** and download the result.

From a gateway config imported by a connector, **click “Push back”** on one of its APIs to export
it to that gateway's own format: Kong for a Kong connector, **AWS API Gateway**, **Azure API
Management** or **Apigee API proxy** for theirs (see [Connectors](../bring-in/connectors.mdx)).

With the API, use the target key with `POST /v1/export/{tenant}/preview` and the export job
endpoints — see [Export a specification](./export-a-spec.md).

## What survives, and what is declared

When the API came from the same gateway, what the import recorded is written back as it was:

- **AWS API Gateway** re-emits each operation's integration, auth, request validator and
  extensions, and the API's settings, validators, CORS and authorizers.
- **Azure API Management** re-emits the policy documents it read. From an ARM template it rebuilds
  each recorded fact — backend, rate limits, rewrites, CORS, IP filters, preserved policy XML — at
  the scope it came from.
- **Apigee** re-emits the bundle it read.

From any other source, each target derives what it needs from the API and says so in the
fidelity report and the export's losses:

| Situation | What the export does |
| --- | --- |
| An operation with no recorded upstream | AWS: a `mock` integration. Azure: no backend in the API policy. Envoy: a cluster named after the service. Traefik and Apigee: a placeholder URL. |
| A gateway policy (rate limit, rewrite, CORS) recorded by name only | Not emitted — its configuration is not in the API. |
| Authentication | Kong and Apigee emit `apiKey` / OAuth policies, and AWS emits an `api_key` scheme. Envoy, Istio and Traefik authenticate outside the route table, so authentication is a declared loss there. |
| Two routes with the same method and path (different hosts or headers) | AWS, Azure and Apigee hold one per method and path; the second is merged and reported. |
| A route that matches any method | AWS uses `x-amazon-apigateway-any-method`. An Azure operation needs a method, so the route is dropped and reported. |
| Path parameters | Apigee's `MatchesPath` has no parameter names, so `{userId}` comes back as `{segment1}`. |
| A header match by prefix or suffix | Traefik writes it as an anchored `HeaderRegexp`, so it comes back as a regex. |

Every target checks its own output before you download it. The check re-imports the artifact and
applies the product's rules: Envoy's `RouteConfiguration` structure, Istio's `VirtualService`
schema, Traefik's router and service references, API Gateway's import rules, APIM's policy
schema, and an Apigee bundle's references.

## Related

- [Understand export fidelity](./export-fidelity.md) — how the fidelity report is worked out.
- [Export to an API client](./export-to-an-api-client.md) — Hoppscotch and Thunder Client
  collections.
- [Import Envoy and Istio routes](../bring-in/envoy-istio-route-import.md) and
  [Import reverse-proxy routes](../bring-in/reverse-proxy-route-import.md) — the import side.
- [Supported formats](../bring-in/supported-formats.md) — every format and the versions written.

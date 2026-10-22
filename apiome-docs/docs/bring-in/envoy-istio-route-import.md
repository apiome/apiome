---
title: "Import Envoy and Istio routes"
description: "Import service-mesh routing from Envoy xDS or Istio VirtualService files."
sidebar_position: 10.5
tags: [import, envoy, istio, gateway, service-mesh]
---

In a service mesh, the routing configuration is often the only machine-readable record of which paths
exist. Apiome reads it from **Envoy** route configuration or **Istio** `VirtualService` manifests and
turns each route into an **operation**. Every operation is marked **inferred**: the route table says
where requests go, not what they carry.

## What you can import

| You have | Importer | Import it as |
| --- | --- | --- |
| An Envoy bootstrap (`static_resources` with listeners and clusters) | Envoy xDS routes (`envoy-xds`) | One file |
| An Envoy `RouteConfiguration` (`name` and `virtual_hosts`) | Envoy xDS routes (`envoy-xds`) | One file |
| An xDS `DiscoveryResponse` (`type_url` and `resources`), YAML or JSON | Envoy xDS routes (`envoy-xds`) | One file |
| A bootstrap and the `rds.yaml` / `cds.yaml` files it loads through filesystem xDS | Envoy xDS routes (`envoy-xds`) | One archive with all the files |
| An Istio `VirtualService`, alone or in a multi-document YAML stream with its `Gateway` and `DestinationRule` | Istio VirtualService (`istio`) | One file |
| A GitOps directory with one Istio resource per file | Istio VirtualService (`istio`) | One archive with all the files |

Envoy xDS v3 resources are read in full; xDS v2 resources are read through the same rules. Istio
`networking.istio.io/v1`, `v1beta1` and `v1alpha3` are read the same way.

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises the file and picks the importer. The API lands in the [Catalog](./catalog.mdx) as a
non-publishable item, because a route table has no request or response schemas. To make it a Project,
add schemas and [convert it to OpenAPI](./convert-to-openapi.md).

## What Apiome reads

| Envoy | Istio | Becomes |
| --- | --- | --- |
| A virtual host | A `VirtualService` | A **service** |
| A route | One entry of an `http` rule's `match` list (a rule with no `match` matches everything) | An **operation** |
| `path`, `prefix`, `path_separated_prefix`, `safe_regex` | `uri.exact`, `uri.prefix`, `uri.regex` | The operation's **path** — mapped exactly as Gateway API's `Exact`, `PathPrefix` and `RegularExpression` path types |
| A `:method` header match | `method.exact`, or a `method.regex` such as `GET\|HEAD` | The operation's **method** (one operation per method); otherwise `ANY` |
| Header and query-parameter matches | `headers` and `queryParams` | Required **parameters**, with the matched value |
| `domains` | `hosts` | **Servers**. `https` when the virtual host requires TLS, the listener terminates TLS, or an Istio `Gateway` serves the host over HTTPS |
| `cluster`, `weighted_clusters` | `route[].destination` (host, port, subset, weight) | The operation's **backends** |
| `timeout`, `retry_policy`, rewrites, `cors`, `rate_limits`, `direct_response`, `redirect` | `timeout`, `retries`, `rewrite`, `redirect`, `directResponse`, `fault`, `mirror`, `corsPolicy`, `headers` | **Policies** named on the operations they apply to |
| A `jwt_authn`, `oauth2` or `basic_auth` HTTP filter | — | The operation's **security** (`bearer`, `oauth2`, `basic`) |

A regular-expression path becomes a template: `^/orders/[0-9]{6}/lines/[0-9]+$` becomes
`/orders/{param1}/lines/{param2}`, and the original pattern is kept.

## One rule for every gateway format

Every gateway importer — Kong, Gateway API, Envoy, Istio, Traefik, nginx, HAProxy, Consul and Tyk —
maps matches through the same table, so the same route imports the same operation whichever format
it came from:

- **Paths** are exact, prefix or regular-expression matches, named as Gateway API names them.
- **Matched values** on header and query parameters are written as the bare value for an exact
  match, and as `prefix:acme-`, `suffix:…`, `contains:…` or `regex:…` otherwise. A match with no
  value only requires the parameter to be present.
- **Inferred or declared** depends only on the format: Kong and Gateway API declare their routes,
  every other gateway format is marked inferred. A path parameter recovered from a regular
  expression is always marked inferred.

## What is declared, not imported

Some routing has no equivalent HTTP operation. Apiome lists each of these in the import's coverage
ledger instead of dropping it silently:

- **Envoy:** CONNECT routes (`connect_matcher`), routes that match only a fraction of traffic
  (`runtime_fraction`) or only gRPC requests (`grpc`), inverted header matches, and routes, listeners
  or clusters delivered at runtime through RDS, LDS or ADS.
- **Istio:** `delegate` rules, `tls` and `tcp` route blocks, `sourceLabels` and `withoutHeaders`
  matches, and resources that shape the mesh but route nothing (`DestinationRule`, `Gateway`,
  `ServiceEntry`, `Sidecar`, and `security.istio.io` policies).

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | No route can be imported: an Envoy route configuration has no virtual hosts or routes, or no Istio `VirtualService` has an `http` rule. |
| `INPUT_REFERENCE_UNRESOLVED` | An Envoy route names a cluster the file defines no cluster for, or an Istio destination names a subset its `DestinationRule` does not define. A file that declares no clusters, or takes them from a control plane, is not checked. |
| `INPUT_TRUNCATED` | The file is cut off — for example it ends with `timeout: 15` (a duration with no unit) or with a service host that stops inside `.svc.cluster.local`. |
| `FORMAT_MISMATCH` | The file is not Envoy or Istio configuration. |
| `INPUT_MALFORMED`, `INPUT_ENCODING_INVALID` | The YAML is not valid, or the file is not UTF-8. |

## What is inferred

On the catalog item, every service, route and parameter is **inferred**: a route table is evidence of an API, not a declaration of one. Those entities carry a badge with the evidence, and the
**Provenance** filter on the **Overview** tab narrows to them — see
[Declared, inferred and synthesized](./inference-provenance.mdx).

## Related

- [Supported formats](./supported-formats.md): the versions these importers read.
- [Import reverse-proxy routes](./reverse-proxy-route-import.md): the same idea for Traefik, nginx,
  HAProxy, Consul and Tyk configuration.
- [Import an AWS API Gateway export](./aws-api-gateway-import.md),
  [Import an Azure API Management API](./azure-api-management-import.md) and
  [Import an Apigee proxy bundle](./apigee-proxy-bundle-import.md): the same idea for API gateways.

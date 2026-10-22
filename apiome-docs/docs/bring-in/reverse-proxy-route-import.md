---
title: "Import reverse-proxy routes"
description: "Import routes from Traefik, nginx, HAProxy, Consul or Tyk configuration."
sidebar_position: 10.6
tags: [import, traefik, nginx, haproxy, consul, tyk, gateway]
---

For many APIs the reverse-proxy configuration is the only record of which paths exist. Apiome reads
**Traefik**, **nginx**, **HAProxy**, **Consul** and **Tyk** configuration and turns each route into an
**operation**. Every operation is marked **inferred**: a proxy configuration says where requests go,
not what they carry.

## What you can import

| You have | Importer | Import it as |
| --- | --- | --- |
| A Traefik dynamic configuration (`http.routers`, `http.services`, `http.middlewares`) in YAML or TOML | Traefik dynamic config (`traefik`) | One file |
| A directory the Traefik file provider watches (routers, services and middlewares in separate files) | Traefik dynamic config (`traefik`) | One archive with all the files |
| Traefik `IngressRoute` and `Middleware` resources (`traefik.io` or `traefik.containo.us`) | Traefik dynamic config (`traefik`) | One file |
| An nginx configuration with `server` and `location` blocks | nginx configuration (`nginx`) | One file |
| An `nginx.conf` and the files it `include`s | nginx configuration (`nginx`) | One archive with all the files |
| An `haproxy.cfg` | HAProxy configuration (`haproxy`) | One file |
| An `haproxy.cfg` and the map files its `use_backend` rules read | HAProxy configuration (`haproxy`) | One archive with all the files |
| Consul service definitions, a catalog export, or `service-router` / `ingress-gateway` entries, in JSON or HCL | Consul service definitions (`consul`) | One file, or one archive for a set |
| A Tyk classic API definition (`api_id` and `proxy.listen_path`) | Tyk API definition (`tyk`) | One file |
| A Tyk classic API definition and its policies file | Tyk API definition (`tyk`) | One archive with both files |
| A Tyk OAS API definition (an OpenAPI 3 document with `x-tyk-api-gateway`) | Tyk API definition (`tyk`) | One file |

## Import it

Import the file like any other specification: in the [import wizard](./import-wizard.mdx), with
`apiome import`, or through the REST API (see [Import a specification](./import-a-spec.md)). Apiome
recognises the file and picks the importer. If the wizard offers more than one format, choose the
importer named in the table above.

The API lands in the [Catalog](./catalog.mdx) as a non-publishable item, because a proxy
configuration has no request or response schemas. To make it a Project, add schemas and
[convert it to OpenAPI](./convert-to-openapi.md). A **Tyk OAS** definition is the exception: it is a
real OpenAPI document, so its paths and schemas are imported as written and only the Tyk gateway
settings are marked inferred.

## What Apiome reads

| Format | Becomes an operation | Path match | Hosts and scheme | Kept as policy |
| --- | --- | --- | --- | --- |
| Traefik | Each alternative of a router's `rule` (`&&`, `\|\|` and parentheses are expanded) | `Path` exact, `PathPrefix` prefix, `PathRegexp` regex | `Host(…)`; `https` when the router has `tls` | Middlewares, with `chain` expanded; `basicAuth` also gives the operation `basic` security |
| nginx | Each `location` a client can reach | `=` exact, no modifier or `^~` prefix, `~` / `~*` regex | `server_name`; `https` when `listen` has `ssl` | `proxy_set_header`, timeouts, `limit_req`, `allow` / `deny` and the other carried directives, as nginx inherits them |
| HAProxy | Each alternative of a `use_backend` condition, plus `default_backend` | `path` exact, `path_beg` / `path_dir` prefix, `path_reg` regex | `hdr(host)` ACLs; `https` when `bind` has `ssl` | `http-request` actions, `timeout`, `option` and the other section directives |
| Consul | Each `service-router` route, plus one catch-all per registered HTTP service that no router describes | `PathExact`, `PathPrefix`, `PathRegex` | `ingress-gateway` listener `Hosts` | Destination settings such as `RequestTimeout` and `NumRetries`, and `service-splitter` splits |
| Tyk classic | Each `white_list` and `ignored` path, once per method in `method_actions`, at `listen_path` + path | Exact, with `{param}` segments as path parameters | The `domain`, when one is set | Per-path rules (`cache`, `hard_timeouts`, `validate_json`, …), the global rate limit and CORS, and the policies that grant access |

Methods come from Traefik `Method(…)`, nginx `limit_except … { deny all; }`, HAProxy `method` ACLs,
Consul `Methods` and Tyk `method_actions`; otherwise the operation's method is `ANY`. Header and
query matches become required **parameters** with the matched value, written the same way for every
gateway format (see [One rule for every gateway format](./envoy-istio-route-import.md#one-rule-for-every-gateway-format)). A regular-expression path
becomes a template: `^/orders/[0-9]{6}$` becomes `/orders/{param1}`, and the original pattern is
kept.

A Consul service with a Fabio-style `urlprefix-/v2/orders` tag gets a prefix operation at that path.
That is a naming convention, not a route declaration, so the operation records where its path came
from.

## nginx: a documented subset

nginx configuration can compute values at runtime (`map`, `geo`, `set`), branch on them (`if`) and
jump between locations (`try_files`, `error_page`, named locations). Apiome does not try to evaluate
any of that. It reads a fixed list of directives, keeps another list as policy, and declares
everything else. The [Supported formats](./supported-formats.md#format-nginx) page lists every
directive in each group.

- **Read:** `http`, `server`, `listen`, `server_name`, `location`, `proxy_pass` and the other
  `*_pass` handlers, `upstream`, `return`, `root`, `alias`, `limit_except`, `internal`, `include`,
  `ssl_certificate`, `auth_basic` and `auth_request`.
- **Declared, not read:** `if`, `map`, `geo`, `split_clients`, `set`, `try_files`, `error_page`,
  named and internal locations, nested locations, a `proxy_pass` to a variable, regular-expression
  server names, includes that are not in the import, `stream` blocks and Lua, njs or Perl handlers.
- **Anything else** is declared by name (for example `directive.gzip`).

## What is declared, not imported

Some configuration has no equivalent HTTP operation. Apiome lists each of these in the import's
coverage ledger instead of dropping it silently:

- **Traefik:** TCP and UDP routers, negated matchers, `ClientIP` and `HostRegexp` conditions, TLS
  options and certificates, and `serversTransports`.
- **HAProxy:** sections in `mode tcp`, conditions on the client address, TLS, stick-table counters,
  the request body or Lua, `path_end` and `path_sub` matches, a computed `use_backend` whose map file
  is not in the import, and the `global` section.
- **Consul:** gRPC and TCP listeners and services, inverted header matches, resolver failover and
  redirects, Connect upstreams, and configuration entries other than the router, splitter,
  resolver, defaults and ingress gateway.
- **Tyk:** `validate_json` request schemas (kept as policy, not as message types), an inline GraphQL
  schema, version selection by header or URL, custom middleware scripts, and middleware for an
  `operationId` the OpenAPI document does not have.

## When an import is refused

| Error code | Why |
| --- | --- |
| `INPUT_SEMANTIC_INVALID` | Nothing can be routed: no Traefik router has a rule, no nginx `server` block exists, no HAProxy `frontend` binds a listener, a Consul service has no port or address, or a Tyk API has no `listen_path` or no versions. |
| `INPUT_REFERENCE_UNRESOLVED` | A route names something the import does not declare: a Traefik service or middleware, an nginx `upstream`, an HAProxy backend or ACL, a Consul service or resolver subset. An nginx file with an `include` that is not in the import is not checked. |
| `INPUT_TRUNCATED` | The file is cut off — for example nginx ends in the middle of a directive, HAProxy ends with a `server` address that stops partway, or JSON ends with an object still open. |
| `FORMAT_MISMATCH` | The file is not configuration for the chosen importer. |
| `INPUT_MALFORMED`, `INPUT_ENCODING_INVALID` | The file has a syntax error (an unknown HAProxy section, a missing nginx `}`, a Traefik rule that does not parse, bad JSON or HCL), or it is not UTF-8. |

## Related

- [Supported formats](./supported-formats.md): the versions these importers read, and the full nginx
  directive list.
- [Import Envoy and Istio routes](./envoy-istio-route-import.md): the same idea for a service mesh.
- [Import an AWS API Gateway export](./aws-api-gateway-import.md),
  [Import an Azure API Management API](./azure-api-management-import.md) and
  [Import an Apigee proxy bundle](./apigee-proxy-bundle-import.md): the same idea for API gateways.

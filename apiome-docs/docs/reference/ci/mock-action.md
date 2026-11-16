---
title: "mock-action (GitHub Action)"
description: "Inputs, outputs and behaviour of the apiome/mock-action portable mock runtime."
sidebar_position: 4
tags: [ci, reference]
generated: apiome-docs/scripts/sync-action-pages.mjs from mock-action/README.md
---

> This page is `mock-action/README.md`, copied by `yarn workspace apiome-docs sync:action-pages` — edit the README, not this page.

Start a version-pinned [portable mock](../mock-runtime/portable-mock-runtime.md) for the rest of a CI
job, get a loopback-only service URL back, and have the container removed automatically when the
job ends — however it ends.

```yaml
- uses: apiome/apiome/mock-action@v1
  id: mock
  with:
    bundle: petstore-1.0.0-mock-bundle.json
    image: ghcr.io/apiome/apiome-mock:0.5.0   # pin a version or a digest
    conformance: "true"                        # prove the runtime before trusting it

- run: npm test
  env:
    API_BASE_URL: ${{ steps.mock.outputs.service-url }}
```

Export the bundle in an earlier step (or commit it) with
`GET /v1/versions/{tenant}/{project_id}/{version_record_id}/mock/bundle`.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `bundle` | *(required)* | Bundle to serve. Workspace-relative or absolute; paths outside the workspace are refused. |
| `image` | `ghcr.io/apiome/apiome-mock:latest` | Runtime image. **Pin a version tag or digest in CI** — `latest` drifts. |
| `port` | `0` | Host port. `0` picks a free one, so parallel jobs on one runner never collide. |
| `host` | `127.0.0.1` | Interface to publish on. Loopback keeps the mock reachable from the job and nothing else. |
| `wait` | `60` | Seconds to wait for readiness before failing. |
| `conformance` | `false` | Run the shared conformance corpus against the started runtime. |
| `require-signature` | `false` | Refuse to serve an unsigned bundle. |
| `bundle-secret` | `""` | Shared HMAC secret for signature verification. Pass a repository secret. |
| `pull` | `true` | Pull the image before starting it. |
| `protocols` | `http` | Protocols the job needs, comma-separated: `http` (always served), `graphql`, `connect`, `grpc`, `events`. See [Protocols](#protocols). |
| `grpc-port` | `0` | Host port for the native gRPC listener when `protocols` includes `grpc`. `0` picks a free one. |
| `broker-bootstrap` | `""` | `host:port` list of the broker event channels publish through. **Required** with `events`. |
| `broker-password-env` | `""` | **Name** of an environment variable on this step holding the broker password. Forwarded by name, never on a command line. |
| `network` | `""` | Docker network to attach the runtime to, so it can reach a broker on that network by name. |

## Outputs

| Output | Meaning |
|---|---|
| `service-url` | Base URL **including** the version mount — what your tests should call. |
| `base-url` | Runtime root, for `/health` and `/ready`. |
| `mount` | `/{tenant}/{project}/{version}` prefix. |
| `bundle-digest` | Digest of the served bundle. |
| `runtime-version` | Version of the runtime serving it. |
| `container` | Container name (removed automatically). |
| `port` | Host port that was published. |
| `graphql-url` | GraphQL endpoint (POST queries here) when `protocols` includes `graphql`; empty otherwise. |
| `connect-url` | Connect base URL — methods answer at `/pkg.Service/Method` under it — when `protocols` includes `connect`; empty otherwise. |
| `grpc-url` | Native gRPC target as `host:port` (what `grpcurl` and `@grpc/grpc-js` take) when `protocols` includes `grpc`; empty otherwise. |
| `protocols-served` | Every protocol the runtime reports served on `/ready`, comma-separated, whether you asked for it or not. |

`bundle-digest` and `runtime-version` are two of the four identities a release-proof mock
attestation records. To turn a job's run into that evidence, follow it with `apiome-mock attest` —
see [mock-release-attestation.md](../mock-runtime/mock-release-attestation.md).

## Protocols

By default the action starts an HTTP mock and gives you `service-url`. Name more protocols to get
an endpoint for each:

```yaml
- uses: apiome/apiome/mock-action@v1
  id: mock
  with:
    bundle: shop-2.0.0-mock-bundle.json
    image: ghcr.io/apiome/apiome-mock:<multi-protocol release>   # see below
    protocols: graphql,connect

- run: npm test
  env:
    API_BASE_URL: ${{ steps.mock.outputs.service-url }}
    GRAPHQL_URL: ${{ steps.mock.outputs.graphql-url }}
    CONNECT_URL: ${{ steps.mock.outputs.connect-url }}
```

GraphQL and Connect ride on the same listener as HTTP. `grpc` also publishes the runtime's native
gRPC listener on `grpc-port` and returns it as `grpc-url`.

**The runtime decides, not the action.** After the runtime is ready, the action reads the
`protocols` object on its [`/ready`](../mock-runtime/portable-mock-runtime.md)
response. If the pinned image cannot serve a protocol you asked for, the step fails before your
tests run, with the runtime's reason for each protocol:

```text
The pinned runtime cannot serve every requested protocol — pin an image that does, or drop them from "protocols".
  graphql: this runtime serves HTTP only: GraphQL routes are not in mock bundle format v1, …
```

An older image whose `/ready` has no `protocols` object is treated as HTTP-only. Current images
serve HTTP only. GraphQL, Connect, native gRPC and events arrive with the portable runtime's
multi-protocol release (XPC-5.2). Until then, asking for them fails the step with this message.

### Broker channels: bring your own broker

Event channels publish through a broker. **The action never starts one.** It stays a single
container, and the job owns the broker. Asking for `events` without `broker-bootstrap` fails the
step immediately, before anything is pulled.

The recipe below starts [Redpanda](../mock-runtime/event-mock-brokers.md)
on a named network, then attaches the mock to that network. Redpanda is started in a step rather
than under `services:` because a service container cannot be given the `redpanda start` flags that
set its advertised address.

```yaml
- name: Start a broker for the mock
  run: |
    docker network create apiome-ci
    docker run --detach --name redpanda --network apiome-ci \
      docker.redpanda.com/redpandadata/redpanda:v24.2.7 \
      redpanda start --mode=dev-container --smp=1 --memory=512M \
        --kafka-addr=0.0.0.0:9092 --advertise-kafka-addr=redpanda:9092
    timeout 60 sh -c 'until docker exec redpanda rpk cluster health | grep -qE "Healthy:.+true"; do sleep 2; done'

- uses: apiome/apiome/mock-action@v1
  id: mock
  with:
    bundle: orders-1.0.0-mock-bundle.json
    image: ghcr.io/apiome/apiome-mock:<multi-protocol release>
    protocols: events
    network: apiome-ci
    broker-bootstrap: redpanda:9092
    # broker-password-env: BROKER_PASSWORD   # for a SASL broker; set BROKER_PASSWORD in env
```

For a broker that needs a password, put the secret in the step's `env` and give its **name** in
`broker-password-env`. The action forwards it to the container as `APIOME_MOCK_BROKER_PASSWORD`,
by name. The value never appears on a command line or in the run log.

## What it guarantees

**A safe service URL.** The runtime publishes on `127.0.0.1` by default, so nothing off the runner
can reach the mock. No credential ever appears in the URL, and the bundle carries none: a bundle is
credential-free by construction (see [the bundle format](../mock-runtime/mock-bundle-format.md)). A
signing secret, when configured, is forwarded to the container **by name** rather than on a command
line, where the process table would expose it to every process on the runner.

**Automatic cleanup.** The action registers a `post` step, which GitHub runs after the job whether
it passed, failed, or was cancelled. The container's last 200 log lines are attached first, in a
collapsed group: once the container is gone they are the only record of why the mock answered as it
did, and a post step cannot tell whether the job passed, so they are always attached rather than
guessed at. Cleanup itself never fails the job — a container that is already gone is the outcome it
wanted anyway.

**Reported digests.** The runtime version and bundle digest are published as outputs and written to
the job summary. A green suite proves nothing if nobody can tell which artifact answered it; assert
the digest in a later step to prove the job ran against the bundle it intended to:

```yaml
- run: |
    test "${{ steps.mock.outputs.bundle-digest }}" = "sha256:90591f2f…" \
      || { echo "mock served an unexpected bundle"; exit 1; }
```

## Behavior parity

`conformance: "true"` runs the corpus shipped inside the image against the container that just
started — the same corpus the hosted runtime is held to, covering routing, request validation,
scenarios, sessions, chaos, templates, and fixture packs. To compare a *hosted* deployment against
a portable one response by response, use the runtime's parity command:

```bash
apiome-mock parity \
  --hosted-url https://mock.apiome.dev --hosted-mount /acme/petstore/1.0.0 \
  --portable-url http://127.0.0.1:8775
```

## Development

```bash
cd mock-action
yarn test   # node --test, no dependencies
yarn lint   # syntax check every script
```

The action is plain Node with **no dependencies and no bundling step**, so what runs on a runner is
exactly what is committed here and reviewable in a pull request.

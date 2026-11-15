---
title: "Event mock brokers"
description: "Bind an AsyncAPI mock to Kafka: dev broker, bindings, keys, security."
sidebar_position: 12
tags: [mocks, asyncapi, kafka]
---

A published AsyncAPI version with its mock on serves its event channels over **WebSocket** and
**Server-Sent Events** on the mock host. That suits a browser, but not a Kafka consumer under
test. A **broker binding** tells the hosted mock which Kafka cluster belongs to the version, so
events can reach real consumers there.

There are two kinds of broker:

- **The dev broker**: a single-node Redpanda that `docker compose --profile broker` starts beside
  the local stack.
- **Your own cluster**: any Kafka-compatible broker you can reach on a public address, with TLS
  and SASL if you need them.

Until a version has a binding, its **Mock** cell on **Published** reads *Events · WebSocket/SSE
only — no broker bound*. Once it has one, the cell reads *Events · Kafka broker bound, plus
WebSocket/SSE*.

<Screenshot id="mock-broker-binding" alt="Two AsyncAPI versions on Published: 1.1.0's Mock cell says a Kafka broker is bound, 1.0.0's says WebSocket/SSE only, no broker bound." />

:::note What ships now
This release stores, checks and tests the binding. The producer that publishes example messages to
bound topics is the next step on the roadmap. Until it ships, a binding is configuration that you
can test, and events still arrive over WebSocket/SSE.
:::

## The dev broker

The local stack has no broker by default, and nothing in it waits for one. To add one:

```bash
docker compose --profile broker up --build --wait
```

This adds a `redpanda` service: Redpanda in dev-container mode, unauthenticated, with one core and
512 MiB of memory. It does not keep data between runs. You reach its Kafka API at:

| From | Bootstrap |
| --- | --- |
| Inside the stack (`rest`, `mock`) | `redpanda:9092` |
| Your machine | `localhost:19092` (change it with `APIOME_DEV_BROKER_HOST_PORT`) |

`rest` and `mock` already have `APIOME_MOCK_DEV_BROKER_BOOTSTRAP=redpanda:9092`. While the
profile is running, the mock's `/health` reports the broker too:

```bash
curl -s http://localhost:8775/health
# {"status": "ok", "broker": "reachable"}
```

Without the profile, the `redpanda` host doesn't exist on the stack network. `/health` then
answers `{"status": "ok"}` exactly as before.

To bind a version to the dev broker, pass its address with no TLS and no SASL:

```bash
curl -X POST "$APIOME_API/v1/versions/acme-corp/$PROJECT_ID/$VERSION_ID/mock/broker-bindings" \
  -H "X-API-Key: $APIOME_API_KEY" -H 'Content-Type: application/json' \
  -d '{"protocol": "kafka", "bootstrap": ["redpanda:9092"]}'
```

The response carries `"devBroker": true`.

## Bind your own cluster

A binding belongs to one version and one protocol. Only `kafka` works for now; `mqtt` and `amqp`
are reserved and refused with `broker-protocol-unsupported`.

```bash
curl -X POST "$APIOME_API/v1/versions/acme-corp/$PROJECT_ID/$VERSION_ID/mock/broker-bindings" \
  -H "X-API-Key: $APIOME_API_KEY" -H 'Content-Type: application/json' \
  -d '{
    "protocol": "kafka",
    "bootstrap": ["b-1.kafka.example.com:9096", "b-2.kafka.example.com:9096"],
    "tls": {"enabled": true, "verify": true},
    "saslMechanism": "SCRAM-SHA-512",
    "credential": {"username": "apiome-mock", "password": "…"},
    "clientIdPrefix": "acme-mock"
  }'
```

| Field | What it is |
| --- | --- |
| `bootstrap` | One to sixteen `host:port` entries, as a list or a comma-separated string. The port defaults to `9092`. Write IPv6 literals in brackets (`[2001:db8::1]:9092`). A scheme, `user@`, path or query is refused. |
| `tls.enabled` | Connect over TLS (`SSL`, or `SASL_SSL` with a mechanism). |
| `tls.verify` | Check the broker's certificate and hostname. Defaults to `true`; turn it off only for a self-signed test cluster. |
| `saslMechanism` | `PLAIN`, `SCRAM-SHA-256` or `SCRAM-SHA-512`. Leave it out for a broker with no authentication. |
| `credential` | `{username, password}`, required with a mechanism. It is write-only (see [Security model](#security-model)). |
| `clientIdPrefix` | The Kafka `client.id` prefix Apiome's connections use, so your broker's logs and quotas can tell them apart. Defaults to `apiome-mock`. |

A version can have only one `kafka` binding; a second one gets `409 broker-binding-exists`. To
move to another cluster, delete the binding and create a new one.

### Test the binding

```bash
curl -X POST "$APIOME_API/v1/versions/acme-corp/$PROJECT_ID/$VERSION_ID/mock/broker-bindings/$BINDING_ID/test" \
  -H "X-API-Key: $APIOME_API_KEY"
# {"status": "reachable", "summary": "reachable", "bootstrap": "b-1.kafka.example.com:9096",
#  "brokers": 3, "topics": 42, "checkedAt": "…", "cached": false}
```

A test opens one connection to a bootstrap host, completes the TLS and SASL handshakes and reads
the cluster metadata. It never creates, reads or writes a topic. Apiome counts the brokers the
metadata lists but never connects to their advertised addresses.

When the broker can't be reached, the result says why:

| `summary` | Meaning |
| --- | --- |
| `unreachable: auth` | The broker refused the credential or its mechanism. A wrong password shows up here. |
| `unreachable: credential-unavailable` | The stored credential can't be opened on this deployment (its master key isn't configured). Rotate it. |
| `unreachable: address-disallowed` | A host now resolves to a private address, or doesn't resolve at all. |
| `unreachable: tls` | The TLS handshake or the certificate check failed. |
| `unreachable: timeout` | No answer within 5 seconds per host. |
| `unreachable: connect` | The connection was refused or dropped. |
| `unreachable: protocol` | Something answered, but not as a Kafka broker. |

The broker's own error text is never returned, because it can quote the username. A result is
reused for 60 seconds (`"cached": true`). Rotating the credential runs a fresh test.

### Rotate, list and delete

| Call | What it does |
| --- | --- |
| `GET …/mock/broker-bindings` | Lists the version's bindings as metadata. Also says whether this deployment can store a credential (`encryptionConfigured`) and gives the dev broker's address while the profile is configured (`devBrokerBootstrap`). |
| `POST …/{id}/rotate` | Replaces the credential in place. The body is `{"credential": {"username", "password"}}`. The binding keeps its id, address and flags. |
| `DELETE …/{id}` | Removes the binding and its sealed credential. The version's events go back to WebSocket/SSE only. |

The full request and response schemas are on the [Mock server REST reference](../rest/mock-server.md).

## Who can do it

The binding is part of the version's mock configuration, so it uses the existing **versions**
permissions (there is no new role resource):

- Listing needs `versions:view`.
- Create, rotate, test and delete need `versions:edit`. You must also be the version's creator or
  a workspace administrator, as for every other mock setting.

Every create, rotate, test and delete is written to the workspace's access audit as
`mock.broker_binding.create`, `.rotate`, `.test` or `.delete`. Each row records the binding id,
version, protocol, bootstrap, TLS flags, mechanism and key version, plus the outcome for a test.
It never records the credential.

## Environment

| Variable | Service | Default | Purpose |
| --- | --- | --- | --- |
| `APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS` | rest | unset | Master-key map (`{"1": "<base64 32-byte key>"}`) that seals SASL credentials. Unset: bindings without SASL still work, and storing a credential gets `503 broker-credential-encryption-unconfigured`. |
| `APIOME_BROKER_CREDENTIAL_ACTIVE_KEY_VERSION` | rest | highest in the map | Which key version seals new credentials. |
| `APIOME_MOCK_DEV_BROKER_BOOTSTRAP` | rest, mock | `redpanda:9092` in compose; unset elsewhere | The dev broker's `host:port` list. REST exempts exactly these entries from the address check, and the mock reports them on `/health`. |
| `APIOME_MOCK_BROKER_ALLOW_PRIVATE` | rest | `false` | Lifts the private-address check for broker bindings only. Use it for local development against a broker on your own network, never on a shared deployment. |
| `APIOME_DEV_BROKER_HOST_PORT` | compose | `19092` | The host port the dev broker's Kafka API is published on. |

Generate a master key with:

```bash
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

## Security model

- **Address check before any connection.** Apiome resolves every bootstrap host, and if *any*
  address is private, loopback, link-local (including the cloud metadata address), shared, multicast
  or reserved, the binding is refused with `422 broker-address-disallowed`. A host that doesn't
  resolve is refused too. The check runs again before every test, so a DNS record changed after
  the binding was saved can't redirect Apiome inward. A plaintext test connects to the exact
  address that passed the check. A TLS test connects by hostname, because certificate checks need
  the name.
- **Two exceptions, both explicit.** The dev broker's exact `host:port` is exempt only while
  `APIOME_MOCK_DEV_BROKER_BOOTSTRAP` names it. Every other host and port stays checked.
  `APIOME_MOCK_BROKER_ALLOW_PRIVATE=true` turns the address check off for broker bindings only. The
  shape rules (no scheme, credentials or path) always apply.
- **The credential is ciphertext, and only ciphertext.** The username and password are sealed
  together with AES-256-GCM under a per-credential data key wrapped by a versioned master key.
  This is the same envelope scheme as the agent upstream vault, with its own key map and magic, so
  a credential can't be moved into or out of another vault. The table has no plaintext column and
  no digest of the password.
- **Write-only.** No route returns the credential or its ciphertext. A malformed request's `422`
  doesn't echo the body. A test sweeps every `GET` in the API to prove it.
- **Fails closed.** Without a master key, a credential can't be stored, and a stored one can't be
  opened (`unreachable: credential-unavailable`).

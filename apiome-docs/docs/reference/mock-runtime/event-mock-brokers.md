---
title: "Event mock brokers"
description: "Bind an AsyncAPI mock to Kafka and publish its events there."
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

Once a version is bound, the hosted mock **publishes** to Kafka: one message per channel every
interval, and one more whenever you ask (see [What the mock publishes](#what-the-mock-publishes)).
WebSocket/SSE keep working beside it.

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

## What the mock publishes

### Which channels

A channel is published to Kafka when it rides Kafka. That means its `protocol` (or the document's
server protocol) is `kafka`, or the channel or one of its messages declares a `kafka` binding. The
mock sends the messages of the channel's **receive** operations: what a consumer under test
receives.

**The topic** is the channel's Kafka binding `topic` when it declares one. Otherwise it is the
address with its parameters filled in and `/` turned into `.`: `user/signedup` publishes to
`user.signedup`. An address parameter is filled from its first `enum` value, then its first
`examples` value, then its `default`.

Some channels are never published, and the mock says why:

| Status | Meaning |
| --- | --- |
| `supported` | Published to the topic shown. |
| `unsupported: unresolved-address-parameter` | A parameter in the address has no `enum`, `examples` or `default`, so there is no concrete topic. The mock doesn't guess: a guessed topic is one no consumer listens on. |
| `unsupported: invalid-topic` | The resolved topic isn't a legal Kafka topic name (letters, digits, `.`, `_`, `-`; up to 249 characters). |
| `not-kafka` | The channel doesn't use Kafka; it is served over WebSocket/SSE only. |

To see every channel's status, topic and encoding, list them:

```bash
curl -s https://mock.apiome.dev/acme-corp/user-events/1.1.0/__channels__ -H "X-Api-Key: $KEY"
# {"brokerBound": true, "channels": [{"key": "user/signedup", "address": "user/signedup",
#   "kafka": {"support": "supported", "topic": "user.signedup", "unresolvedParameters": []},
#   "messages": [{"name": "UserSignedUp", "encoding": "json"}], "intervalSeconds": 2.0, …}]}
```

### When

- **Every interval.** While the version is published, its mock is on and it has a binding, the mock
  publishes one message per outbound message of every publishable channel every
  `intervalSeconds` (2 seconds). Turn the mock off and publishing stops within one interval.
  Delete the binding and it stops at the next refresh (`APIOME_MOCK_BROKER_REFRESH_SECONDS`,
  30 seconds by default). A private draft mock isn't published on a timer, because there is no
  caller's key to serve it with. Publish it on demand instead.
- **On demand.** Send one message now:

  ```bash
  curl -X POST https://mock.apiome.dev/acme-corp/user-events/1.1.0/__channels__/user/signedup/publish \
    -H "X-Api-Key: $KEY"
  # {"status": "published", "channel": "user/signedup", "topic": "user.signedup", "partition": 1,
  #  "offset": 42, "encoding": "json", "source": "example", "message": "…UserSignedUp"}
  ```

  The JSON body is optional. When you send one, it is the payload. `?message=<name>` picks one of
  several messages, `?__seed=` makes a generated payload repeatable, and `X-Mock-Scenario` picks
  the scenario.

| Answer | When |
| --- | --- |
| `200 published` | The broker acknowledged the record. |
| `404` | No such channel (or the mock is off). |
| `409 no-broker-bound` | The version has no broker binding. |
| `422 unpublishable` | The channel can't be published. `reason` gives its status, such as `unresolved-address-parameter`. |
| `422 rejected` | The payload fails its schema. **Nothing is sent.** `detail` says which field. |
| `429 rate-limited` | The workspace's mock rate or monthly quota is used up. |
| `502 unreachable` | The broker couldn't be reached. `reason` is `auth`, `tls`, `timeout`, `connect`, `address-disallowed` or `credential-unavailable`. |

### The payload

The first of these that exists is used. This is the same order as REST and GraphQL mocks:

1. The body of an on-demand publish.
2. The scenario's override for the channel. Key it `PUBLISH /user/signedup` (or `*` for every
   channel) in the version's scenarios. Its canned body becomes the payload.
3. The message's first declared `examples[].payload`.
4. A fixture-pack `data` value keyed by the channel key (`user/signedup`) or the message name.
5. Data generated from the message schema.

Whatever its source, the payload is checked against the message schema first. **A payload that
fails is never sent.** The publish is answered `422 rejected`, and the periodic producer logs it and
moves on.

### Key, headers and encoding

- **Key.** Taken from the message's Kafka binding `key` schema: its `const`, first `enum`,
  `examples`, `example` or `default`, or a generated value. With no `key` binding the record has
  no key, and the broker picks the partition.
- **Headers.** The first example's `headers`, or values generated from the message's header schema,
  plus `content-type` and `x-apiome-encoding`.
- **Encoding.** Set by the message's `schemaFormat`:

| `schemaFormat` | Record value | `content-type` header |
| --- | --- | --- |
| absent, or a JSON Schema format | UTF-8 JSON, checked against the JSON Schema | `application/json` |
| `application/vnd.apache.avro…` | Schemaless **Avro binary**, written with the message's own Avro schema. Decode it with that same published schema. | `application/vnd.apache.avro+binary` |
| `application/vnd.google.protobuf…` | **Protobuf binary**, from the modelled record type the payload references. A raw `.proto` text payload isn't compiled by the mock and is refused as `unsupported-schema`. | `application/x-protobuf` |

### Usage and limits

Each record sent counts as one mock request toward the workspace's monthly quota and the
**Mock** sparkline. Publishing has its own rate bucket at the workspace's mock requests-per-second
limit. The mock also keeps a daily count per channel, encoding and trigger (`periodic` or
`on-demand`) of records sent and of records refused for failing their schema.

### Brokers stay public

The mock connects only to addresses that pass the [address check](#security-model): the bootstrap
hosts again at connect time, and then **every broker the cluster advertises**. A Kafka client talks
to whatever brokers the cluster metadata lists, so a cluster that advertises a private address is
refused (`address-disallowed`) and nothing is sent.

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
| `APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS` | rest, mock (identical) | unset | Master-key map (`{"1": "<base64 32-byte key>"}`) that seals SASL credentials. Unset: bindings without SASL still work, and storing a credential gets `503 broker-credential-encryption-unconfigured`. |
| `APIOME_BROKER_CREDENTIAL_ACTIVE_KEY_VERSION` | rest | highest in the map | Which key version seals new credentials. |
| `APIOME_MOCK_DEV_BROKER_BOOTSTRAP` | rest, mock | `redpanda:9092` in compose; unset elsewhere | The dev broker's `host:port` list. REST exempts exactly these entries from the address check, and the mock reports them on `/health`. |
| `APIOME_MOCK_BROKER_ALLOW_PRIVATE` | rest, mock | `false` | Lifts the private-address check for broker bindings only. Use it for local development against a broker on your own network, never on a shared deployment. |
| `APIOME_DEV_BROKER_HOST_PORT` | compose | `19092` | The host port the dev broker's Kafka API is published on. |
| `APIOME_MOCK_BROKER_PRODUCER_ENABLED` | mock | `true` | Runs the periodic producer. On a deployment with several mock replicas, leave it on for one replica only, or every replica publishes each interval. On-demand publishing works either way. |
| `APIOME_MOCK_BROKER_REFRESH_SECONDS` | mock | `30` | How often the producer re-reads which versions have a binding. |

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

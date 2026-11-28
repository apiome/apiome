---
title: "Capture for a consumer"
description: "Record a consumer's calls to the hosted mock and read them back."
sidebar_position: 13
tags: [mocks, contracts, pact]
---

**Capture for a consumer** records the calls one consumer makes to a hosted mock, so they can be
turned into that consumer's pact. Point the consumer, or its tests, at the mock and tag each call
with who is calling. Apiome keeps those calls, redacted, as a **capture session** for that consumer
and version. Untagged calls are never recorded, so other callers of the same mock are unaffected.

The mock still answers from the spec, so every captured call already agrees with the provider's
contract. Generating the pact from a session comes later; this page covers recording and reading
back.

## Tag your calls

Send `X-Mock-Capture: <consumer>@<version>` on every request, or set it once in your HTTP client:

```bash
export BILLING_API_URL=https://mock.apiome.dev/acme/billing-api/2.7.0

curl -H 'X-Mock-Capture: orders-ui@3.4.0' "$BILLING_API_URL/invoices/42"
```

- The **consumer** is the name before the last `@`. It can be a slug (`orders-ui`) or a display name
  (`Orders UI`), and may contain an `@` of its own (`@acme/web@1.2.0` is consumer `@acme/web`).
- The **version** is the consumer's own version after the last `@` (`3.4.0`, `3.4.0+a1c9e02`).
- Each part has at most 200 characters, with no leading or trailing spaces and no control
  characters.
- `X-Mock-Capture: off` (or `0`, `false`, `no`) records nothing. The values `on`, `record`, `true`,
  `yes` and `1` still mean [guarded proxy capture](./mock-proxy-capture.md), which is a different
  feature.

The answer is exactly what an untagged call gets, plus two headers:

| Response header | Value |
| --- | --- |
| `X-Mock-Capture` | `queued` — the call will be written within a few seconds; or `not-recorded` |
| `X-Mock-Capture-Session` | `<consumer>@<version>`, when queued |
| `X-Mock-Capture-Reason` | Why the call was not recorded, when it was not |

A call is **not recorded** when the tag cannot be read (for example `orders-ui` with no version), when
a capture URL is unknown, revoked, expired or belongs to another mock version, or when too many calls
are waiting to be written. The mock still serves the call.

## Use a capture URL instead of a header

For a client that cannot add a header, create a private **capture URL**. Calls made under it are
recorded for the consumer and version it names:

```bash
curl -X POST https://api.apiome.dev/v1/tenants/acme/pact-captures/links \
  -H "X-API-Key: $APIOME_API_KEY" -H 'Content-Type: application/json' \
  -d '{"project": "billing-api", "version": "2.7.0", "consumer": "Orders UI", "consumer_version": "3.4.0"}'
```

The answer's `url` is `https://mock.apiome.dev/acme/billing-api/2.7.0/~capture/mcap_…`. Use it as the
consumer's base URL. `…/~capture/mcap_…/invoices/42` is served as `/invoices/42`.

- The token in the URL is shown **once**, in this answer. Apiome stores only its digest; the list
  (`GET …/pact-captures/links`) shows its first characters (`token_prefix`) and whether it is `live`,
  `revoked` or `expired`.
- A link lasts `expires_in_days` (default 7, at most 30).
- `DELETE …/pact-captures/links/{id}` revokes it. Calls through it are still served and, within 30
  seconds, answered `not-recorded`.
- A capture URL tags calls; it does not open a private mock. A private draft mock still needs its
  API key.

## Read a session back

Each mock version, consumer and consumer version has one session. Calls tagged the same way are
added to it.

```bash
curl -H "X-API-Key: $APIOME_API_KEY" \
  'https://api.apiome.dev/v1/tenants/acme/pact-captures/sessions?consumer=orders-ui'

curl -H "X-API-Key: $APIOME_API_KEY" \
  https://api.apiome.dev/v1/tenants/acme/pact-captures/sessions/<session id>
```

A session says when its first and last calls were made, how many calls it holds, how many it could
not take and why, and when it expires. Each call has:

| Field | What it holds |
| --- | --- |
| `method`, `path`, `status` | The request and the answer's status |
| `path_template`, `operation_key` | The spec's path (`/invoices/{id}`) and operation the call matched; `null` when nothing matched |
| `origin` | Where the answer came from: `spec`, `scenario` (an `X-Mock-Scenario` or the version's active scenario), `session` (stateful `X-Mock-Session` data), `chaos` (an injected error), `forced` (`Prefer: code=`), `off-spec` (not in the spec) or `rejected` (the mock refused the request) |
| `scenario` | The scenario in effect, if any |
| `mock_session` | A digest of the `X-Mock-Session` token, so calls of one stateful conversation can be grouped; never the token |
| `via`, `link_id` | `header` or `url`, and the capture URL used |
| `request`, `response` | Query, headers and bodies as stored after redaction |
| `redactions` | Each value removed, with the rule and a reason |

Sessions and calls are paged with `limit` and `cursor`. `DELETE …/sessions/{id}` deletes a session and
its calls, so the next tagged call starts a new one. The routes are listed under
[Pacticipants in the REST reference](../rest/pacticipants.md).

## What is stored

Request and response are stored after the mock's redaction rules, the same rules
[guarded proxy capture](./mock-proxy-capture.md) uses:

- credentials are always removed: `Authorization`, cookies, API-key and token headers, token-like
  query parameters, credential-shaped body fields and JWT-shaped values;
- the version's own `proxyCapture.redaction` rules (extra headers, query parameters, body fields and
  personal-data patterns such as `email`) apply as well;
- a body over 64 KB, or one that is not JSON or text, is left out, and the removal is listed.

The `X-Mock-Capture` and `X-Mock-Session` headers are not stored. If anything credential-shaped is
still found after redaction, the call is **not stored** and is counted on the session as
`credential-residual`.

## Limits and retention

| Limit | Value | When it is reached |
| --- | --- | --- |
| Calls per session | 5,000 | Further calls are counted on the session as `session-full` |
| Live sessions per workspace | 500 | Calls that would open another are counted in the settings' `refused_calls` |
| Retention | 7 days by default, 1–30 | Each call expires that long after it was recorded; a session expires that long after its last call |

`GET /v1/tenants/{t}/pact-captures/settings` shows the retention, the limits and the refused count.
`PUT` with `{"retention_days": 14}` changes the retention; the new value applies to calls recorded from
then on. An expired session or call is never listed and reads as
`404 capture-session-not-found`.

## Who can do what

| Action | Permission |
| --- | --- |
| Tag calls to a mock | Anyone who can call the mock |
| Read sessions, capture URLs and settings | **Pacts** → **View** |
| Create a capture URL | **Pacts** → **Create** |
| Revoke a capture URL | **Pacts** → **Edit** |
| Delete a session; change the retention | **Pacts** → **Delete** |

Creating and revoking capture URLs, deleting sessions and changing the retention are recorded in the
[access audit](../../govern/access-audit.mdx) as `pacts.capture.link.create`,
`pacts.capture.link.revoke`, `pacts.capture.session.delete` and `pacts.capture.settings`. The audit
never holds a capture URL's token.

## Related

- [Guarded proxy capture](./mock-proxy-capture.md) — record a real upstream into fixtures.
- [Pact Broker overview](../../ship/pact-broker/overview.mdx) — where a consumer's pact goes next.
- [Operating Apiome](../../admin/operating-apiome.mdx) — the runtime's capture settings.

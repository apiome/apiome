---
title: Deliver an export to a webhook
description: Push a finished export to a pipeline as a signed, retried webhook.
sidebar_position: 5.27
---

An export ends with a file to download, and a pipeline would have to keep asking whether it is ready.
Webhook delivery pushes the result instead. Apiome sends one signed `POST` to your URL with the export's
file manifest, its fidelity report and the bundle itself. If your endpoint is down, Apiome tries again.

Delivery works on an export job that has finished (see [How an export runs](./export-jobs.mdx)). To
compare the channels, see [Deliver an export](./deliver-an-export.mdx).

## Before you start

- **A public HTTPS endpoint.** Apiome refuses URLs that point into private, loopback or link-local
  networks, such as `localhost`, `10.0.0.0/8` or the cloud metadata address. It checks when you send the
  request and again on every attempt.
- **A shared secret** of 16 to 512 characters that your endpoint also knows. Apiome signs the body with it
  once and never stores it.
- **The `versions:publish` permission.** Sending an export outside the workspace needs the same
  permission as a [git delivery](./deliver-an-export-to-git.md).
- **A completed export.** A dry run has no bundle to deliver, and an export whose download has expired
  has to be run again.

## Deliver an export

Send the job's id, your URL and the secret:

```bash
curl -X POST "$APIOME/v1/export/acme/jobs/$JOB_ID/deliveries/webhook" \
  -H "Authorization: Bearer $APIOME_API_KEY" -H "Content-Type: application/json" \
  -d '{"url": "https://ci.example.com/hooks/apiome", "secret": "'"$WEBHOOK_SECRET"'"}'
```

| Field | What it does |
| --- | --- |
| `url` | The endpoint to send the result to. |
| `secret` | The shared secret the body is signed with. |
| `artifact` | `auto` (the default) puts the bundle inside the body when it is 1 MiB or less, and sends a fetch link otherwise. `fetch` always sends a fetch link. |

Apiome makes the first attempt before it answers. The answer is the delivery run: its `status`, the
receiver's status code and every attempt so far. Every field is in the
[export delivery reference](/reference/rest/export-delivery). The URL is always shown without its query
string, because webhook URLs often carry a token there.

## What your endpoint receives

A JSON body with `"schemaVersion": "export.webhook-delivery.v1"` and `"event": "export.delivered"`:

| Key | What it holds |
| --- | --- |
| `deliveryId` | The delivery's id, the same on every retry. |
| `createdAt` | When the delivery was requested. |
| `export` | The artifact, version, target (or `multi` with every `targets` entry) and snapshot hash. |
| `manifest.files` | Every file in the bundle, with its path, size and media type. |
| `fidelity` | The `summary` (tier, preserved share, counts), the full `report`, and a `reportUrl` that opens it in Export studio. |
| `artifact` | The bundle: `filename`, `mediaType`, `sizeBytes`, `sha256`, and either the content or a fetch link. |
| `job.downloadPath` | The job's own download path, for callers that have Apiome credentials. |

**Inline bundles** (`artifact.delivery: inline`) carry `content`. A single file is UTF-8 text
(`encoding: utf-8`), and a multi-file bundle is its zip in base64 (`encoding: base64`).

**Large bundles** (`artifact.delivery: fetch`) carry a `url` and an `expiresAt` instead. The link needs no
Apiome sign-in, because its signature is the credential. It works for 24 hours or until the export's
download expires, whichever comes first. Check the file you download against `sha256`.

## Verify the signature

Every request carries these headers:

| Header | Value |
| --- | --- |
| `X-Apiome-Signature` | `sha256=` plus the hex HMAC-SHA256 of the raw body, keyed with your secret. |
| `X-Apiome-Event` | `export.delivered` |
| `X-Apiome-Delivery` | The delivery's id. A retry sends the same id, so you can drop duplicates. |
| `X-Apiome-Delivery-Attempt` | `1` for the first attempt, then `2`, `3` and `4`. |

Compute the HMAC over the bytes exactly as they arrived, before parsing the JSON, and compare it in
constant time:

```python
import hashlib
import hmac

def is_from_apiome(body: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

This is the same scheme as Apiome's other outgoing webhooks, so one verifier serves both.

## Retries

Answer with any `2xx` status to accept the delivery. Otherwise, the answer decides what happens next:

| Your endpoint answers | What Apiome does |
| --- | --- |
| `2xx` | The run is `delivered`. |
| Nothing (refused connection, timeout), `408`, `425`, `429` or `5xx` | The run is `retrying`. Apiome tries again after 10 seconds, 1 minute and 5 minutes, waiting longer when a `429` or `503` sends `Retry-After`. After four attempts, the run is `failed`. |
| `3xx` | The run is `failed`. Redirects are not followed, so send the final URL. |
| Any other `4xx` | The run is `failed`. Your endpoint refused the delivery, so it is not retried. |

Every retry sends the same body with the same signature.

## When a delivery fails

A failed run keeps every attempt, with your endpoint's status code and the start of its response, plus
a stable `errorCode`:

| `errorCode` | What to do |
| --- | --- |
| `export-webhook-delivery-rejected` | Your endpoint answered `3xx` or `4xx`. Check its URL, and that it accepts the signature. |
| `export-webhook-delivery-attempts-exhausted` | Four attempts got no answer or a `5xx`. Fix the endpoint, then deliver again. |
| `export-webhook-delivery-destination-refused` | The URL resolved to a private address on an attempt. Use a public endpoint. |

Some problems are refused before anything is sent:

- An invalid URL or secret answers `400` with `export-webhook-delivery-request-invalid`.
- A URL that resolves to a private address answers `400` with `export-webhook-delivery-destination-refused`.
- An unfinished job answers `409`, and an expired download `410`. Run the export again, then deliver it.

A bundle that needs a fetch link answers `409` with `export-webhook-delivery-fetch-url-unavailable` when
the server has no public address configured. An administrator sets `APIOME_API_PUBLIC_URL`, or raises
`APIOME_EXPORT_WEBHOOK_INLINE_MAX_BYTES` so the bundle fits in the body.

## See past deliveries

`GET /v1/export/{tenant}/jobs/{job_id}/deliveries/webhook` lists a job's deliveries, newest first, with
every attempt. Every delivery is also written to the audit log as `export.webhook_delivery`, with your
endpoint's host but not its full URL.

---
title: Deliver an export to object storage
description: Upload a finished export to an S3-compatible bucket with a predictable layout.
sidebar_position: 5.28
---

An export ends with a file to download. Data platforms expect artifacts in a bucket instead, at
predictable paths. Apiome can upload a finished export to any S3-compatible bucket: AWS S3, MinIO,
Cloudflare R2 or Ceph. The files land under a prefix you choose, partitioned by artifact, version and
target, next to a manifest that lists every file with its SHA-256.

Delivery works on an export job that has finished (see [How an export runs](./export-jobs.mdx)).

## Before you start

- **A bucket, and a key that can write to it.** The key needs `s3:PutObject` on the prefix you deliver
  to.
- **The `projects:edit` permission** to store the key in the workspace, and **`versions:publish`** to
  deliver, the same permission as a [git](./deliver-an-export-to-git.md) or
  [webhook](./deliver-an-export-to-a-webhook.md) delivery.
- **A completed export.** A dry run has no files to deliver, and an export whose download has expired
  has to be run again.

## Store the bucket credential

Store the key once. Apiome seals it in the workspace's credential vault as soon as it arrives:

```bash
curl -X POST "$APIOME/v1/export/acme/storage-credentials" \
  -H "Authorization: Bearer $APIOME_API_KEY" -H "Content-Type: application/json" \
  -d '{"name": "data-lake", "accessKeyId": "'"$AWS_ACCESS_KEY_ID"'",
       "secretAccessKey": "'"$AWS_SECRET_ACCESS_KEY"'", "region": "eu-west-1"}'
```

| Field | What it does |
| --- | --- |
| `name` | A name unique in the workspace. |
| `accessKeyId`, `secretAccessKey` | The key pair. |
| `sessionToken` | Optional, for temporary credentials. |
| `endpointUrl` | An S3-compatible endpoint, such as `https://minio.example.com` or `https://<account>.r2.cloudflarestorage.com`. Leave it out for AWS S3. |
| `region` | The bucket's region. The default is `us-east-1`; Cloudflare R2 uses `auto`. |
| `forcePathStyle` | `true` addresses buckets as `<endpoint>/<bucket>/…`, which most self-hosted stores (MinIO, Ceph) need. |

The answer is the credential's `id`, endpoint, region and the **last four characters** of the access
key id. Neither the secret nor the whole key id is ever shown again, by any route or in any log.
`GET /v1/export/acme/storage-credentials` lists the workspace's credentials, and
`DELETE /v1/export/acme/storage-credentials/{id}` removes one.

An `endpointUrl` that resolves to a private network address, such as `localhost` or `10.0.0.0/8`, is
refused, both when you store it and at every delivery.

## Deliver an export

Send the job's id, the credential and where the files go:

```bash
curl -X POST "$APIOME/v1/export/acme/jobs/$JOB_ID/deliveries/object-storage" \
  -H "Authorization: Bearer $APIOME_API_KEY" -H "Content-Type: application/json" \
  -d '{"credentialId": "<credential id>", "bucket": "data-lake", "prefix": "exports/apis"}'
```

| Field | What it does |
| --- | --- |
| `credentialId` | The stored credential to upload with. |
| `bucket` | The bucket. |
| `prefix` | The key prefix everything is written under. Empty means the bucket root. |
| `partitioning` | The partitions below the prefix, in order: any of `artifact`, `version` and `target`. The default is all three. `[]` writes straight under the prefix. |

The answer is the delivery run: its `status`, the `keyPrefix` it wrote under, every object with its size
and SHA-256, and the manifest's key. Every field is in the
[export delivery reference](/reference/rest/export-delivery).

## What lands in the bucket

With the default partitioning, an export of **Orders API 1.4.0** to OpenAPI 3.1 under `exports/apis`
writes:

```text
exports/apis/orders/1.4.0/openapi-3.1/openapi.yaml
exports/apis/orders/1.4.0/openapi-3.1/schemas/pet.json
exports/apis/orders/1.4.0/openapi-3.1/manifests/<sha256>.json
exports/apis/orders/1.4.0/openapi-3.1/manifest.json
```

- **Every file the export produced, at its path in the bundle.** Each object carries its SHA-256 in
  `x-amz-meta-sha256`. A multi-target export uses `multi` as its target and keeps one directory per
  target.
- **A content-addressed manifest** at `manifests/<sha256>.json`, named after its own SHA-256. It lists
  every object's key, size and SHA-256, with the artifact, version, target, snapshot hash and fidelity
  summary. It holds no timestamp or job id, so delivering the same export again writes the same
  manifest to the same key.
- **`manifest.json`**, a copy of the manifest from the latest delivery to that prefix.

The manifests are written **last**, so when one is there, every object it lists is too. To consume a
delivery, read `manifest.json`, then fetch and check each object against its `sha256`.

Partition values are made safe for keys: anything other than letters, digits, `.`, `_` and `-`
becomes `-`. An artifact without a slug uses its id, and a version without a label is `unversioned`.

## When a delivery fails

A delivery that cannot finish still answers with a run, `status: failed` and a stable `errorCode`. The
objects written before the failure are listed, and the message never contains the key or secret.

| `errorCode` | What to do |
| --- | --- |
| `export-object-storage-delivery-credential-missing` | No credential with that id exists in the workspace. Store one. |
| `export-object-storage-delivery-credential-unavailable` | The credential can't be opened on this deployment, because its encryption key changed. Store it again. |
| `export-object-storage-delivery-credential-rejected` | The provider refused the key pair, or the session token expired. Store a valid one. |
| `export-object-storage-delivery-permission-denied` | The key can't write to the bucket. Grant it `s3:PutObject` on the prefix. |
| `export-object-storage-delivery-bucket-missing` | The bucket doesn't exist at that endpoint. Check its name, the region and the endpoint. |
| `export-object-storage-delivery-endpoint-refused` | The endpoint resolves to a private address. Use a public one. |
| `export-object-storage-delivery-endpoint-unreachable` | The endpoint didn't answer. Check the URL and region. |
| `export-object-storage-delivery-upload-failed` | The provider refused an upload for another reason; the message says which. |

An invalid bucket name, a prefix with `..` or a repeated partition answers `400`. An unfinished job
answers `409`, and an expired download `410`; run the export again, then deliver it.

## See past deliveries

`GET /v1/export/{tenant}/jobs/{job_id}/deliveries/object-storage` lists a job's deliveries, newest
first. Every delivery is also written to the audit log as `export.object_storage_delivery`, and every
stored or deleted credential as `export.storage_credential.created` or `.deleted`, without secrets.

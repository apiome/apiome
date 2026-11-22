---
title: "Run Apiome locally"
description: "Start the local stack, load the sample data and sign in."
sidebar_position: 2
tags: [setup]
---

Bring the local spine up with Docker and load the dev seed (the `acme-corp` tenant and the published
`petstore-sample` project):

```bash
docker compose up --build --wait      # postgres, migrate, seed, rest (:8000), mcp (:8765)
docker compose run --rm seed          # idempotent; ensures the dev tenant + sample exist
```

Then sign in to the UI with the dev login `ada@example.com` / `apiome-dev` and **click “Control
Panel”** on the launcher to open **Home**. The default service ports are:

| Service | URL |
|---|---|
| REST API | `http://localhost:8000` (interactive docs at `/docs`) |
| MCP server | `http://localhost:8765` (MCP endpoint at `/mcp`) |
| UI | the Next.js app (`/ade` launcher, `/ade/dashboard`) |

Every how-to page shows the **UI**, **REST**, and (where applicable) **CLI** way to do the same
thing, plus a short *verify* step.

## Use an S3 store (optional)

`docker compose up` also starts MinIO (API `http://localhost:9000`, console `http://localhost:9001`)
and creates its bucket. REST keeps documents in the database until you add
`APIOME_DOCUMENT_STORE=s3` to `.env` and restart; see
[Document store](../admin/document-store.mdx#the-bundled-minio-local-development).

## Add a Kafka broker (optional)

AsyncAPI mocks can be bound to a Kafka broker. The stack doesn't include one unless you ask for it:

```bash
docker compose --profile broker up --build --wait   # adds redpanda (Kafka API on :19092)
```

This starts a single-node Redpanda. The stack reaches it at `redpanda:9092`, and your machine
reaches it at `localhost:19092`. While it runs, `curl -s http://localhost:8775/health` on the mock
returns `"broker": "reachable"`. Without `--profile broker`, nothing changes and no service waits
for a broker. To bind a version to it, see [Event mock brokers](../reference/mock-runtime/event-mock-brokers.md).

## Where next

[Sign in](./sign-in.mdx) with `ada@example.com` / `apiome-dev`, then follow the Getting started pages
in order — they walk the spine from import to a published, browsable spec. The repository's
`README.md` and the
[Golden Path](./index.mdx) cover the same path from
the repository side.

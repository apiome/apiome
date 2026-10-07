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

Then sign in to the UI with the dev login `ada@example.com` / `apiome-dev` and open **Control
Panel → Dashboard**. The default service ports are:

| Service | URL |
|---|---|
| REST API | `http://localhost:8000` (interactive docs at `/docs`) |
| MCP server | `http://localhost:8765` (MCP endpoint at `/mcp`) |
| UI | the Next.js app (`/ade/dashboard`, `/ade/studio`) |

Every how-to page shows the **UI**, **REST**, and (where applicable) **CLI** way to do the same
thing, plus a short *verify* step.

## Where next

[Sign in](./sign-in.mdx) with `ada@example.com` / `apiome-dev`, then follow the Getting started pages
in order — they walk the spine from import to a published, browsable spec. The project
[README](https://github.com/apiome/apiome/blob/main/README.md) and the
[Golden Path](https://github.com/apiome/apiome/blob/main/docs/GOLDEN_PATH.md) cover the same path from
the repository side.

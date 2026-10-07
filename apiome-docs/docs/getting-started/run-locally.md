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

## Walk the spine

The spine is the end-to-end path a specification takes through Apiome. One page covers each step:

1. [Import a specification](../bring-in/import-a-spec.md)
2. [Edit classes and properties](../build/edit-classes-and-properties.md) and
   [paths and operations](../build/edit-paths.md)
3. [Lint and check quality](../build/lint-and-quality.md)
4. [Cut a version](../ship/cut-a-version.md)
5. [Publish a version](../ship/publish-a-version.md)
6. [Browse published specs](../ship/browse-published-specs.md)
7. [Export a spec](../ship/export-a-spec.md) with the [CLI](../reference/cli-quickstart.md)
8. Query published specs with [MCP](../reference/mcp-quickstart.md)

The project [README](https://github.com/apiome/apiome/blob/main/README.md) (“Your first project in
~10 minutes”) and the [Golden Path](https://github.com/apiome/apiome/blob/main/docs/GOLDEN_PATH.md)
(the executable definition of “the product works”) cover the same path from the repository side.

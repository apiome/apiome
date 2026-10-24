---
title: "Catalog to project journey test"
description: "The end-to-end test that walks Catalog import through export on every pull request."
sidebar_position: 12
tags: [content]
---

The Catalog to project journey is one Playwright test that walks the whole path RC6 ships, through
the real app, REST API and database. Each screen has its own unit tests; this one notices when a
change to one screen breaks the hand-off to the next. RC6-H1
([#6208](https://github.com/apiome/apiome/issues/6208)) added it.

## What it walks

| Step | Screen | What must happen |
| --- | --- | --- |
| 1 | Export studio | The route shows **Not available yet**, which proves the run sees released pages only |
| 2 | Catalog → **Import to catalog** | A RAML spec pasted into **Clipboard Paste** is stored in the catalog |
| 3 | Catalog | Filtering by the spec's title finds the item, and it opens |
| 4 | Catalog item → **Convert to OpenAPI** | The conversion creates a new project, linked from the item |
| 5 | Projects → **Edit project** | A new description is saved, and is still there after a reload |
| 6 | Versions → **New version** | The new version appears in the table |
| 7 | Version menu → **Publish** | The version shows **Published** |
| 8 | Version menu → **Unpublish** | **Published** goes away |
| 9 | Version menu → **Export** | The **Export** dialog produces a Protobuf file |

The test signs in through a mock GitHub provider; nothing else is mocked. Each run titles its spec
with a timestamp, so runs against the same database never collide.

## When it runs

- **On every pull request** that changes `apiome-ui`, `apiome-rest` or `apiome-db`, through the
  **Catalog Journey (RC6-H1)** workflow. It can also be started by hand from the Actions tab.
- With **no preview override**: `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES` is empty when the app is
  built and when it runs, so held-back features stay hidden, as they are for users.

The workflow builds the app for production and starts the database, migrations and REST API with
Docker Compose. It picks free ports for each run, so runs can share a machine. When a run fails,
its Playwright report and the stack's logs are attached to the run.

## Run it locally

With Postgres, the migrations and the REST API running (`docker compose up --wait` from the
repository root), run this from `apiome-ui/`:

```bash
yarn test:e2e:catalog-journey
```

To test a production build, as CI does:

```bash
NEXT_PUBLIC_APIOME_PREVIEW_FEATURES= yarn build
CATALOG_JOURNEY_USE_BUILD=1 yarn test:e2e:catalog-journey
```

## When a screen changes

The test waits for elements by `data-testid`, never for a fixed time. If you rename or remove a
`data-testid` the journey waits on, the unit test `tests/catalog-journey-config.test.ts` fails and
names it, so you find out before the journey runs. Update the spec,
`apiome-ui/e2e/journey/catalog-project-journey.spec.ts`, in the same pull request.

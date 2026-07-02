# Golden Path — end-to-end spine smoke test

This is the executable definition of *"the product works."* One golden path runs the whole spine
end to end and is the regression net that subsequent RC work must not break (RC1-0.1, #3608):

```
import OpenAPI → edit a class & a path → lint → cut a version → publish
            → view in browse → export OpenAPI + download via CLI → query via MCP
```

There are two ways to run it: the **automated** smoke test (used in CI and locally) and the
**manual checklist** (a human walks the same path through the UI).

---

## Automated smoke test

The automated path is exercised against a clean `docker compose up`. The root `docker-compose.yml`
brings up the full spine: **postgres → migrate → seed → rest (:8000) → mcp (:8765)**.

### One command

```bash
scripts/golden_path/run.sh
```

This brings the stack up (`docker compose up --build --wait`), loads the dev seed data, runs the
harness, and tears the stack down. Flags: `--keep` (leave the stack up afterwards), `--no-build`
(reuse existing images).

### Or step by step

```bash
docker compose up --build --wait        # postgres, migrate, seed, rest, mcp
docker compose run --rm seed            # idempotent; ensures the dev tenant + API key exist
python scripts/golden_path/smoke.py     # run the golden path; exits non-zero on any failure
```

The harness (`scripts/golden_path/smoke.py`) requires `httpx` and `openapi-spec-validator`, both of
which ship with `apiome-cli`'s dependencies — run it under that environment, e.g.
`uv run --project apiome-cli python scripts/golden_path/smoke.py` (this is what `run.sh` does).

### What each step asserts

| # | Step | What it does |
|---|------|--------------|
| 1 | Health | `GET /health` on REST (:8000) and MCP (:8765) become ready. |
| 2 | Import OpenAPI | `POST /v1/tenants/{tenant}/imports` with `fixtures/petstore.openapi.yaml`, polls the job to `completed`, then commits. |
| 3 | Edit a class | `PUT /v1/classes/{tenant}/{class_id}` — sets a description on each class (the same endpoint the UI editor calls). |
| 4 | Edit a path | `PUT /v1/paths/{tenant}/{version}/{path_id}` — sets path metadata. |
| 5 | Cut a version | `POST /v1/versions/{tenant}/{project}` — pushes a new revision (exercises the versioning endpoint). |
| 6 | Publish | `POST /v1/versions/.../{version}/publish` with `visibility: public` (and a revision note). The server enforces publish gates: valid OpenAPI, every class documented, no un-acknowledged breaking changes. |
| 7 | Lint | Fetches the reconstructed OpenAPI for the published version and validates it with `openapi-spec-validator`; asserts the edited class and the paths are present. |
| 8 | View in browse | `GET /v1/browse/tenants/{tenant}/projects/{project}/versions` lists the published version. |
| 9 | Export + download via CLI | Runs the real `apiome spec export` CLI, then re-validates the downloaded document. |
| 10 | Query via MCP | Speaks the MCP streamable-HTTP protocol (`initialize` → `tools/call`): `ping`, `spec.list`, and `project.list` all surface the published project. |

The harness imports into a uniquely-named project per run (`golden-path-petstore-<run-id>`), so it is
safe to run repeatedly and in parallel against a persistent database. Configuration is via
`APIOME_*` env vars (see the docstring at the top of `smoke.py`).

### Notes / known limitations surfaced by this path

- **"Lint"** here is structural validation of the reconstructed OpenAPI plus the server-side publish
  gates (class documentation + breaking-change check). The product's interactive A–F quality score
  is being promoted from the UI's localStorage to a backend service in #3609; when that lands the
  lint step can assert against it.
- **The released artifact is the imported, edited revision.** In the current data model a revision's
  paths are authored on that revision and are not carried across a version cut (the cut copies
  classes only), so the harness publishes the revision that holds the full path set. Carrying paths
  across a cut is tracked as follow-up work.
- The sample document uses object request/response bodies that reference component schemas (the
  path model is class-centric); inline `type: array` response bodies do not currently round-trip
  through reconstruction.

---

## Manual checklist

Run the same path by hand against a running stack + UI. Tick each box; the run is green only if all
pass start to finish.

1. **Start the stack:** `docker compose up --build --wait` and load seed data
   (`docker compose run --rm seed`). Bring up the UI (`yarn workspace apiome-ui dev`). Sign in
   with the seeded dev user (**ada@example.com** / **apiome-dev**, tenant **acme-corp**).
2. **Import:** in the dashboard, **open the Import dialog**, choose **OpenAPI**, upload
   `scripts/golden_path/fixtures/petstore.openapi.yaml`, and **run the import**. Confirm a project
   ("Golden Path Petstore") and version **1.0.0** are created with the **Pet** and **Error** classes
   and the **/pets** and **/pets/{petId}** paths.
3. **Edit a class:** open the **Pet** class in the editor, **change its description**, and **save**.
4. **Edit a path:** open the **/pets** path, **edit it** (e.g. summary/metadata), and **save**.
5. **Lint:** check the **quality/lint badge** on the version and confirm there are no blocking
   findings (every class has a description).
6. **Cut a version:** use **Create/Cut version** to push a new revision (e.g. **1.1.0**).
7. **Publish:** **publish** a version as **public** and provide a revision note. Confirm it shows as
   published.
8. **View in browse:** open **apiome-browse**, find the project, and confirm the **published
   version is listed** and the reconstructed OpenAPI renders.
9. **Export + download via CLI:**
   ```bash
   apiome --base-url http://localhost:8000 spec export \
     --tenant acme-corp --project golden-path-petstore --version 1.0.0 --output petstore.json
   ```
   Confirm a valid OpenAPI document is written.
10. **Query via MCP:** point an MCP client at `http://localhost:8765/mcp` and confirm `spec.list`
    (or `project.list`) returns the published project.

---

## CI

`.github/workflows/golden-path.yml` runs the automated path (full `docker compose up` + harness) on
pushes/PRs that touch the spine. It is intended to be a **required status check** on `main` — the
golden path going red is the signal that the spine has regressed.

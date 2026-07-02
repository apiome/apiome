# Testing — coverage across the spine

This is the map of how the **MVP spine** is tested and gated in CI (RC1-3.1, #3616). The spine is the
golden path defined in [`GOLDEN_PATH.md`](./GOLDEN_PATH.md):

```
import OpenAPI → edit a class & a path → lint → cut a version → publish
            → view in browse → export OpenAPI + download via CLI → query via MCP
```

Three layers gate a merge:

| Layer | Where | What it proves | CI workflow |
|-------|-------|----------------|-------------|
| **End-to-end** | `scripts/golden_path/smoke.py` | The whole spine works against a real `docker compose` stack (postgres → migrate → seed → rest → mcp). | `golden-path.yml` |
| **REST suite** | `apiome-rest/tests` (pytest) | Every REST router — including the golden-path endpoints — behaves, with coverage reported. | `apiome-rest-test.yml` |
| **UI suite** | `apiome-ui/tests` (Jest + RTL) | The editors (designer, paths) and the proxy layer behave, with coverage reported. | `apiome-ui.yml` |
| **Contract** | both suites, one shared file | The endpoints the UI calls match the endpoints REST exposes. | both of the above |

A red golden path means the spine regressed; a red REST/UI suite means an endpoint or editor regressed.

---

## REST tests (`apiome-rest`)

```bash
cd apiome-rest
uv sync
uv run pytest                       # full suite, no database required
uv run pytest --cov                 # with coverage (term + coverage.xml)
```

The suite is **self-contained**: it runs green with no external services. A few cross-cutting concerns
are neutralised once, centrally, in `tests/conftest.py` so individual route tests stay focused and
deterministic:

- **Rate limiting is disabled.** `RateLimitMiddleware` (#3612) keeps a process-wide fixed-window
  counter. Across a full suite the cumulative request count would trip the `429` limit and fail
  otherwise-passing tests as a function of suite size/order. The dedicated `test_rate_limit.py`
  re-enables and exercises the limiter explicitly.
- **The RBAC guard defaults to "allow"** and the legacy-API-key actor lookup
  (`get_fallback_creator_user_id_for_tenant`) returns `None`, keeping the permission guard out of
  Postgres. `test_permission_guard.py` exercises the real predicate.
- **Dependency overrides are snapshotted and restored** around every test, so a test that raises before
  its own teardown cannot leak auth overrides into the next test.

### Live-database integration tests

A small number of tests assert against a real Postgres (e.g. the `mcp_v_public_specs` view contract).
They follow the repo convention of skipping unless `DATABASE_URL` is set:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/apiome uv run pytest
```

The `requires_db` marker is registered for this class of test. In CI the gating job leaves
`DATABASE_URL` unset (so they skip); full database coverage is the `golden-path.yml` workflow's job.

---

## UI tests (`apiome-ui`)

```bash
cd apiome-ui
yarn test                 # Jest unit + component (RTL) tests
yarn test:coverage        # with coverage (text + coverage/coverage-summary.json + lcov/html)
yarn test:e2e             # Playwright (requires a running dev server)
```

Component tests cover the **paths** editor (extensive, pre-existing) and the **class designer** editor
toolbar (`tests/EditorToolbar.test.tsx`) — project/version gating, the canvas/code view switch, tag
management, and the export menu — without the database or the heavy canvas runtime.

CI (`apiome-ui.yml`) runs `yarn test:coverage` against a Postgres service and publishes a coverage
summary to the job summary plus an uploaded artifact.

---

## The UI ↔ REST contract

`scripts/golden_path/contract.json` is the single source of truth for the golden-path REST operations
and which surface owns each one. Both suites read it:

- `apiome-rest/tests/test_golden_path_contract.py` asserts every operation exists in the REST
  OpenAPI surface with its HTTP method.
- `apiome-ui/tests/contract/rest-golden-path-contract.test.ts` asserts the UI proxy routes
  (`src/app/api/**`) still call the operations the UI owns (`"ui": true`).

Matching is structural (per path segment), so the two sides' differing parameter names don't matter. If
an endpoint is renamed, moved, or dropped on either side, the contract goes red — update the JSON and
[`GOLDEN_PATH.md`](./GOLDEN_PATH.md) together when a change is intentional.

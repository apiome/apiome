# apiome project guidelines

- Bump OpenAPI version in apiome-rest when any changes are made.
- Bump package.json version when changes are made to the appropriate project.
- Mark items complete in their respective ROADMAP files in private-suite where applicable.
- Every change updates the Docusaurus site in `apiome-docs/` in the same PR: the affected pages, regenerated screenshots (`yarn docs:screenshots`), regenerated REST / CLI / MCP reference where relevant, and a release-notes entry. `yarn docs:check` must pass. Until `apiome-docs/` is on `main`, write the same content under `docs/guide/` and list it in the PR.


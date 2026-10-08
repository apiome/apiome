# apiome project guidelines

- Bump OpenAPI version in apiome-rest when any changes are made.
- Bump package.json version when changes are made to the appropriate project.
- Mark items complete in their respective ROADMAP files in private-suite where applicable.
- Every change updates the Docusaurus site in `apiome-docs/` in the same PR: the affected pages, regenerated screenshots (`yarn docs:screenshots`), regenerated REST / CLI / MCP reference where relevant, and a release-notes entry. Each issue's **Documentation (Docusaurus)** section (marker `<!-- apiome-docs-tasks:v1 -->`) lists what the PR owes, and the PR body lists the docs pages and screenshot ids touched. `yarn docs:check` must pass — CI runs it on every PR and fails on bad front matter, orphan pages, broken internal links, screenshots missing a theme or an image, stale screenshots and a stale REST reference (see `apiome-docs/docs/admin/contribute-to-the-docs.mdx`). Until `apiome-docs/` is on `main`, write the same content under `docs/guide/` and list it in the PR.


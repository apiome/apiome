# Repository binding (GNC-2.1, #4737)

The **Repository** tab of the Versions dashboard: bind a draft version to a repository branch and
source path, and decide what happens when that branch moves.

| Piece | Where |
|---|---|
| Panel | `src/app/components/ade/bindings/VersionBindingPanel.tsx` |
| Rules (framework-free) | `lib/draft-bindings.ts` |
| BFF routes | `src/app/api/projects/[projectId]/bindings/**` |
| Styles | `globals.css`, the *Repository binding (GNC-2.1, #4737)* section |
| Tests | `tests/version-binding-panel.test.tsx`, `tests/draft-bindings-model.test.ts`, `tests/api/bindings-routes.test.ts`, `tests/bindings-css.test.ts` |

## What the panel is for

Importing a spec from a repository leaves a snapshot. **Binding** leaves a relationship: this draft
is the API review unit of that branch and that path, and the digest of the files it resolved to is
remembered as the base later pushes are measured against.

The panel is built around one rule: **a ref update is never a change**. When a bound branch moves —
through a provider webhook, or because somebody pressed *Check for updates* — a **sync candidate**
appears saying which commit the branch left and which it arrived at. The draft is untouched until
somebody applies or dismisses it, and whichever they choose is recorded in `workflow_audit`.

## Reading it

- The version picker defaults to the **first draft**, because a published version cannot be bound.
- A bound draft shows its `owner/repo @ branch · path`, the commit and the `sha256:` source digest
  it is in sync with, when that last moved, and a link to browse the source at that commit.
- The badge reads **In sync**, **Update available** (something is waiting to be decided),
  **Released**, or **Repository removed** — the last because a binding whose registration is gone is
  history that can never be read from again, and saying only "released" would hide why.
- *Previously bound to* lists the rows this version has had before. Nothing is deleted.

## Deciding an update

A pending candidate offers two buttons.

- **Mark in sync** (`applied`) records that the draft is in sync with that commit. apiome-rest
  re-reads the source at that commit first, so the digest it stores is one that was actually
  fetched. It does **not** modify the draft.
- **Dismiss** leaves the binding exactly where it is.

A candidate raised by a webhook names a commit and nothing more, so the panel says *"The files at
that commit have not been read yet"* rather than claiming they are unchanged — the one sentence in
this surface that must never be a guess (`candidateContentChanged` returns `null`, not `false`).

`superseded` is what the system records when a newer update replaces an older one; the BFF refuses
to forward it, so a hand-made request cannot rewrite history nobody observed.

## The BFF routes

Every route resolves the tenant **from the session**, signs the caller's apiome-rest token, and
forwards only what `lib/draft-bindings.ts` whitelists. They add **no permission rules of their own**:

| Route | apiome-rest | Enforced upstream |
|---|---|---|
| `GET /api/projects/{id}/bindings?version=` | `GET …/versions/{v}/binding` | `projects:view` |
| `POST /api/projects/{id}/bindings?version=` | `POST …/versions/{v}/binding` | `versions:edit` **and a proven repository read** |
| `DELETE /api/projects/{id}/bindings?version=` | `DELETE …/versions/{v}/binding` | `versions:edit` |
| `POST /api/projects/{id}/bindings/check?version=` | `POST …/binding/check` | `versions:edit` + a proven read |
| `POST /api/projects/{id}/bindings/candidates/{cid}?version=` | `POST …/binding/candidates/{cid}` | `versions:edit` (+ a proven read to apply) |

**A credential never travels through the browser.** A private repository is read with a *stored*
linked-account token resolved server-side; a `token` field in a hand-made body is dropped rather
than forwarded, because forwarding it would turn the panel's request into a 422 it cannot explain —
and because it would be a secret in a request log.

A refusal keeps apiome-rest's status **and** its stable `binding-*` code, which
`bindingErrorMessage` turns into something the reader can act on ("The stored credential cannot read
that repository. Link an account with access and try again.") rather than "something went wrong".

## Styles

`.bnd-*` is layout only. Everything with a skin is borrowed: `FormField`, `Input`,
`.hive-control` for the two native pickers, `Badge` for every state, `Alert`, `EmptyState`,
`LoadingState`, and `.mono` for refs, paths and digests. Token-only — no hex, no px beyond
hairlines, no fade — and every holder of a long `owner/repo @ branch · path` or a 71-character
digest has `min-inline-size: 0` and `overflow-wrap: anywhere`, so a narrow window never scrolls
sideways. `bindings-css.test.ts` pins all of it, in both directions: a class the component spells
must be declared, and a declared class must be spelled.

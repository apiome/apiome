# DEMONSTRATION — SDK-EPIC-4: SDK Distribution & Lifecycle

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> tickets' acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [SDK-EPIC-4 #4465](https://github.com/apiome/apiome/issues/4465) · umbrella [SGD #4952](https://github.com/apiome/apiome/issues/4952) |
| Wave | 2 — the SDK lane, end to end |
| Tickets | [3.4 #4494](https://github.com/apiome/apiome/issues/4494) · [3.3 #4493](https://github.com/apiome/apiome/issues/4493) · [2.4 #4488](https://github.com/apiome/apiome/issues/4488) · [2.5 #4490](https://github.com/apiome/apiome/issues/4490) · [4.1 #4495](https://github.com/apiome/apiome/issues/4495) · [4.2 #4496](https://github.com/apiome/apiome/issues/4496) · [4.3 #4497](https://github.com/apiome/apiome/issues/4497) |
| Builds on | SDK-1.1 job/artifact store ✅ · 1.2 sandboxed SPI ✅ · 1.3 preprocessing ✅ · 2.1/2.2 TS+Python ✅ · [2.3 snippets #4487](https://github.com/apiome/apiome/issues/4487) ✅ · 3.1 dialog ✅ · 3.2 CLI ✅ |
| Runtime | ~16 min, plus 20 min prep |
| Audience | API teams whose consumers are currently writing their own clients |
| The one beat | **Publishing a version ships the SDKs — to npm, to PyPI, and as a pull request — without anyone running a generator.** |

> Four of these tickets ([2.4](https://github.com/apiome/apiome/issues/4488),
> [2.5](https://github.com/apiome/apiome/issues/4490), [3.3](https://github.com/apiome/apiome/issues/4493),
> [3.4](https://github.com/apiome/apiome/issues/4494)) hang off epics that were closed in RC4
> while their children stayed open. That's a board wart, not a scope question — the SDK story is
> one story, and this is the video for it.

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | Set the defaults once | Package names stop being a per-generation argument. | 1:30 |
| 2 | Three languages, one spec | Go joins TS and Python — and a server stub joins the clients. | 3:30 |
| 3 | The consumer's side | They never log in. They just get an SDK. | 2:30 |
| 4 | Publish to npm and PyPI | With provenance recording which spec built it. | 3:00 |
| 5 | Deliver as a pull request | The SDK arrives where their code already is. | 2:30 |
| 6 | Publish a version — walk away | Regeneration and delivery happen without you. | 3:00 |

---

## PREP — before anyone is watching (~20 min)

**DO** — Start the stack.

```bash
yarn dev
```

**DO** — Import and publish the petstore spec, and make it public — Act 3 shows the anonymous
Browse surface and needs a published, public version.

**DO** — Point Act 4 at registries you control. **Do not publish to the real npm or PyPI on
camera.** Use a local Verdaccio and a local devpi, or use each registry's dry-run and show the
payload. Decide which in prep and rehearse it, because "publish" is the moment where a live demo
can do something you cannot undo.

**DO** — Create a throwaway GitHub repository for Act 5's pull request, and link it to the tenant
through the existing repository integration at
<http://localhost:3000/ade/dashboard/linked-accounts>. Confirm the PR opens *before* the demo.

**DO** — Pre-generate one artifact of each language so Act 2 has something to compare against if
a job is slow. Generation is minutes-scale work; a progress spinner is not a demo.

**DO** — Set the CLI up in a second terminal.

```bash
export APIOME_BASE_URL=http://localhost:8000
export APIOME_TENANT_ID=acme-corp
export APIOME_API_KEY=sk_devseed00000000000000000000000000000000000000000000000000000000
```

**DO** — Full dry run. Delete the PR and the published packages afterwards.

---

## ACT 1 — Set the defaults once (1:30)

**DO** — Go to <http://localhost:3000/ade/dashboard/projects> → project → **Settings** → **SDK
generation**.

**DO** — Fill in the package scope (`@acme`), the name pattern, the license header, and the
user-agent string. Save.

**SAY**

> Every generated SDK needs a package name, a namespace, a license header and a user-agent. Set
> them per generation and they drift — the TypeScript package is `@acme/petstore`, the Python one
> is `acme_petstore_client`, and the Go module is whatever the person who ran the command typed
> that day.
>
> Set them once, here, and every generator downstream inherits them. Including the ones that run
> without a human — which is Act 6.

---

## ACT 2 — Three languages, one spec (3:30)

**DO** — Open the published version → **Generate SDK**. Show the language cards: TypeScript,
Python, **Go**, and the server stub targets — **FastAPI** and **Express/Hono**.

**DO** — Generate **Go**. Watch the job progress. Download and open it.

**DO** — Show the generated Go client compiling and the package name matching Act 1's defaults —
nobody typed it.

```bash
cd ~/Downloads/petstore-go && go build ./...
```

**DO** — Now generate the **FastAPI server stub**. Open the handler interface.

**SAY**

> Go is the third client language, and it's the one infrastructure buyers ask for first.
>
> But look at the last card, because it's a different kind of thing. That's a *server* stub —
> typed handler signatures and request validation middleware, generated from the same spec.
>
> That closes the design-first loop. Your consumers get a client, and *your own team* gets a
> skeleton whose request validation is derived from the contract rather than written by hand
> and gradually diverging from it. Same preprocessing pipeline underneath — the one that
> synthesizes stable operation IDs and names anonymous schemas, which is why these are usable
> instead of the `Inline_Response_200` soup a naive generator produces.

---

## ACT 3 — The consumer's side (2:30)

*Switch personas. This is the conversion moment and it happens signed-out.*

**DO** — Open a private window. Go to the public Browse page for the published spec. **Do not log in.**

**DO** — Show the **Get SDK** panel: TypeScript, Python and Go, each with an install line and a
download.

**DO** — Open an operation. Show the snippet tabs — install *and* call, in each language.

**DO** — Copy the install line and run it.

**SAY**

> This person does not have an account. They are a developer who was sent a link to your API.
>
> They get a typed client in their language, an install line they can paste, and a working call
> snippet for the operation they're actually looking at. The alternative — the normal thing — is
> that they read your reference docs and write an HTTP wrapper by hand, badly, and then file bugs
> against your API that are really bugs in their wrapper.
>
> And the snippets aren't a second implementation of the SDK. They render from the same canonical
> model the generators read, so a snippet cannot show a call the SDK doesn't support.
>
> Per-project setting, by the way. An internal API turns this off.

---

## ACT 4 — Publish to npm and PyPI (3:00)

**DO** — Return to the dashboard. Project → **Settings** → **Package registries**. Add
credentials for the npm registry and PyPI. Show the secret field is write-only after saving.

**DO** — On the published version, choose **Publish packages**. Run the **dry run** first. Show
the resolved version numbers.

**SAY**

> Semver comes from the version line plus a regeneration counter, not from someone's memory of
> what they published last time.

**DO** — Run it for real against your prep registries. Show the published package.

**DO** — Open the package metadata and point at the provenance block: the spec version, the
generator version, the options hash.

**SAY**

> That provenance line is the part that matters six months from now, when someone asks which
> version of the spec produced the client that is misbehaving in production.
>
> The generator version is pinned in there too, because "regenerate it and see" is not an answer
> when the generator itself has moved on. Identical inputs produce an identical artifact hash —
> that determinism is a gate in the pipeline, not an aspiration.

---

## ACT 5 — Deliver as a pull request (2:30)

**DO** — Choose **Deliver to repository**. Pick the repository linked in prep and the target
branch. Run it.

**DO** — Open the pull request on GitHub. Show the diff — regenerated client, updated version,
and a body that names the spec version it came from.

**SAY**

> Publishing to a registry works for consumers who install packages. It does nothing for the team
> that vendors your client into their monorepo — and there is always one.
>
> So the same artifact arrives as a pull request, into their repository, on their review
> workflow. Their tests run against it before anyone merges.
>
> Note what did *not* happen: we did not ask for a second set of repository credentials. This
> reuses the OAuth integration the repository scanner already holds. One credential store, one
> place to revoke.

---

## ACT 6 — Publish a version and walk away (3:00)

*Close on the automation, because that is what teams actually buy.*

**DO** — Go to the project's **SDK delivery** settings. Create a subscription: on publish →
generate TypeScript, Python, Go → deliver to npm, PyPI and the linked repository.

**DO** — Make a small additive change to the spec. Publish a new version.

**DO** — *Stop talking and let it run.* Show the jobs appearing, then the new package versions,
then the new pull request.

**SAY**

> Nobody ran a generator. Nobody remembered to.
>
> That's the difference between an SDK feature and an SDK *pipeline*. Manual generation decays —
> the first release has SDKs, the fourth doesn't, and by the sixth your published client is a
> liability because it describes an API you no longer have.
>
> A publish event fans out to the whole matrix. Failures dead-letter the way publish webhooks
> already do, so a broken PyPI token doesn't silently swallow the npm release too.
>
> Sixteen minutes ago this was a spec. It's now three clients, a server skeleton, packages on two
> registries with provenance, a pull request in a consumer's repo — and it stays that way on its
> own.

---

## RESCUE — when it goes wrong on stage

**A generation job is still spinning**
Generation is minutes-scale for large specs.
*On stage:* cut to the artifact you pre-generated in prep and narrate over it. Never watch a
progress bar on camera.

**`go build` fails on the generated client**
A preprocessing gap for that spec — worth knowing, terrible to find live.
*On stage:* skip the compile beat, show the generated source instead. File the failure
afterwards; it is a real finding.

**The registry publish 401s**
Credentials belong to a different terminal's environment, or the token expired.
*On stage:* fall back to the dry-run output — it shows the resolved versions and payload, which
is the beat.

**The pull request doesn't open**
The repository link lost its OAuth grant.
*On stage:* show a PR from your dry run. Do not re-authorize on camera.

**Act 6's subscription doesn't fire**
The publish event landed but the worker is not running.
*On stage:* trigger the delivery manually and say plainly that you are doing so.

---

## IF ASKED

**"How is this different from openapi-generator?"**
The preprocessing. Real specs have anonymous schemas, missing operation IDs and unresolved refs,
and a naive generator turns those into unusable code — that is the whole reason teams abandon
generated clients. There is a deterministic pass that bundles refs, synthesizes stable operation
IDs and names inline schemas from context before any template runs.

**"Can we add our own generator?"**
Yes — there's a generator SPI, and generators run in a resource-limited sandbox with no network.
That sandbox is why a community generator is a safe idea rather than a remote-code-execution
story.

**"What happens if a consumer is pinned to an old SDK?"**
The compatibility manifest (SGD-2.1) records which spec versions each artifact supports. That is
also what the API change check consumes in the Git-native flow.

**"Does the Terraform provider / MCP server generator exist?"**
Not in this release — [SDK-4.4](https://github.com/apiome/apiome/issues/4498) and
[SDK-4.5](https://github.com/apiome/apiome/issues/4499) are `Future`. The MCP path is covered
differently and better by the Agent Experience epics, where the tools are hosted and governed
rather than shipped as a file.

---

## Reference

| Surface | Where |
|---|---|
| Projects / SDK settings | <http://localhost:3000/ade/dashboard/projects> |
| Published versions | <http://localhost:3000/ade/dashboard/published> |
| Linked accounts (repo OAuth) | <http://localhost:3000/ade/dashboard/linked-accounts> |
| CLI | `apiome generate sdk --lang go --out ./sdk --wait` |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_SDK_CODE_GENERATION.md` §4 |
| Delivery roadmap | `private-suite/docs/roadmaps/ROADMAP_SDK_GENERATION_AND_DELIVERY.md` |

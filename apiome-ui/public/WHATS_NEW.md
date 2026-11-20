# Apiome 11-2026 RC9

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features/Improvements

- **RC9 begins** — RC8 is complete, and its notes are kept in the **Apiome RC8** release notes. The version on the launcher, in the user menu and on **Help & docs** now names the new release candidate (`RC9`). RC9 is about **Projects** and **Catalog**, with OpenAPI 3.2 / 3.1 and Arazzo 1.1 first
- **Arazzo 1.1 everywhere** — The **Import** dialog accepts Arazzo 1.1 documents and their AsyncAPI sources, the CLI validates each document against the schema for the version it declares, and generated workflows can be written as Arazzo 1.1
- **Arazzo workflows with their API files** — Import a `.zip` (or, with the CLI, a folder) holding an Arazzo workflow and the OpenAPI/AsyncAPI files it calls, and they come in as one workflow with every source resolved; any source that is not found is listed in the import report with the reason
- **See an Arazzo workflow as a flow** — An Arazzo catalog item, and a project whose HEAD revision holds workflows, has a **Workflows** tab: each workflow's steps, inputs and outputs, a step graph of its success and failure paths, and whether each source it calls was found; click a step to open the operation it calls
- **Arazzo changes graded by workflow rules** — `apiome diff`, the diff Action, the publish check and a catalog revision's change report now grade an Arazzo workflow by what its callers depend on: a newly required input, a removed output or source description is breaking; changed parameters, success criteria or `onSuccess` / `onFailure` actions are flagged for review, each with its rule and reason
- **Arazzo exports that explain themselves** — An Arazzo 1.1 step that waits on an event channel (`channelPath`) now imports and exports back unchanged, and the fidelity report on the **Arazzo** card names every difference a round trip finds; Arazzo import and export are checked against official OpenAPI Initiative fixtures and files from Redocly, Spectral and Specmatic
- **Arazzo workflows from the CLI and the API** — `apiome arazzo list` and `apiome arazzo show` read the workflows and steps an Arazzo import stores, with whether each step's operation was found; `apiome arazzo validate` checks a workflow file, or fails a CI job when a stored step did not resolve. The REST API reads one workflow, its steps, or any revision of a catalog item
- **Run an Arazzo workflow against a target** — `apiome arazzo run` (and the REST API) runs a stored workflow step by step against a verification target or a mock: each step's request is built from the workflow inputs and earlier steps' outputs, every success criterion is reported with its expected and actual value, and `goto`, `retry` and `end` actions are followed. Only read-only steps run unless the target allows writes, the run opts in and a fixture names the operation
- **Arazzo: complete, current and visible** — Arazzo 1.0 and 1.1 now work end to end: import a workflow with its API files, read it on the **Workflows** tab or from the CLI, validate it, compare revisions, export it back and run it against a mock or a deployment. **Help & docs** has a new **Arazzo in Apiome** page that shows how the pieces fit
- **OpenAPI exports keep everything** — Export an item imported from OpenAPI 3.0, 3.1 or 3.2 to the same version and it comes back as it was read: callbacks, links, webhooks, `discriminator`, examples, `x-` extensions, `$self`, `itemSchema` and the other constructs are no longer dropped. Exporting to an older version lists each construct that version cannot hold in the loss report. The new **OpenAPI construct matrix** page in **Help & docs** shows the result for every construct and version
- **Bundled, dereferenced or split OpenAPI** — An OpenAPI export's **$ref handling** option writes one bundled file (the default), one file with every `$ref` written out in full, or a `.zip` with one file per path and component that imports back as the same document. A schema that refers to itself is kept as a `$ref` and listed in the fidelity report, or stops the export if you choose **error**. Choose it on the **Options** step, or with `apiome export openapi --refs`
- **OpenAPI 3.2 in Projects** — A project keeps QUERY and custom methods such as `REPORT`, its tag tree (`parent`, `summary`, `kind`), streaming media types (`itemSchema`) and `in: querystring` parameters. **View spec** now names the version the document declares and lists them under **OpenAPI 3.2.0 constructs**. A 3.1 document holds none of them

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: November 20, 2026*


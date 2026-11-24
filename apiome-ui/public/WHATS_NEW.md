# Apiome 11-2026 RC10

We continue to improve the platform based on your feedback with improvements and new features!

---

## Features/Improvements

- **RC10 begins** — RC9 is complete, and its notes are kept in the **Apiome RC9** release notes. The version on the launcher, in the user menu and on **Help & docs** now names the new release candidate (`RC10`). RC10 is about **contracts**: Pact Broker and PactFlow compatibility, bi-directional contract testing, and contract agreements
- **The MCP Catalog opens faster on large catalogs** — the **Servers** grid, its filters and **Analytics** now read each server's tool counts, safety flags and complexity from what was stored at discovery instead of working them out on every load. In a workspace with 2,000 servers of 50 tools each, the grid went from about 8 seconds to under 50 ms, and a filtered view from about 7.5 seconds to under 10 ms. **Analytics** numbers refresh every 30 seconds.
- **Faster search suggestions on the browse site** — the search palette (**⌘K** or **/**) on the public browse site now answers each keystroke in under 50 ms; on a large catalog it took up to a second. It suggests by **name** — organizations, API products, projects, operations, schemas and properties — and shows `40+` when a kind has more matches than it read. **Press ↵ on the first row** to run the full search. The counts in the browse site's top bar and the lists on its home page now refresh every 2 minutes, so a newly published version can take that long to be counted there; its own page and search show it at once.
- **Long lists load a page at a time** — **Export history**, the **MCP capability directory**, **Published versions**, a connector's **Items** and **Refresh runs**, and the admin **Users**, **Tenants**, **Licenses** and **Templates** lists now read one page and offer previous and next page arrows or **Load more**, so a workspace with thousands of rows opens as quickly as a small one. A count that would mean reading every row shows as `10,000+`
- **Pact Broker: pacticipants, versions, branches and tags** — the REST API now keeps the registry Pact tooling names applications by: register a **pacticipant**, record each build as a **version** with its branch and tags, and read every branch's head. A version never changes once recorded, a branch head only moves forward, and deleting a project keeps its pacticipant. **Roles** has a new **Pacts** row for it: **Editor** can view, create and edit; only **Owner** and **Admin** can delete. Verification results and can-i-deploy build on this and are not yet available
- **Pact Broker: publish and fetch pacts** — the Pact CLI and Pact libraries now publish to Apiome. Give `pact-broker publish` or pact-js `publishPacts` your workspace's broker base URL (`…/v1/tenants/<workspace>/pact-broker`) and an API key as the token. Consumers and providers are registered the first time a pact names them, a build's pacts are stored all together or not at all, and identical pacts are stored once, so ten builds of an unchanged pact give the provider one pact to verify. A different pact for a version that already has one is refused; an invalid pact is refused with the place in the file. Verification results and can-i-deploy are not yet available
- **Pact Broker: choose pacts to verify with selectors** — a provider's Pact verifier now fetches the pacts it must verify from Apiome. Send consumer-version selectors such as `{ mainBranch: true }`, `{ matchingBranch: true }` or `{ tag: "prod", latest: true }` with the same broker base URL and token you publish with. Each pact comes back once, with the reasons it was chosen in the words the Pact Broker uses, and an ambiguous selector is refused with the place in the request. You can also read the latest pact of a consumer from a tag or a branch. Environment selectors select nothing until deployments can be recorded, and every pact is pending until verification results are recorded

---

View our YouTube channel [here](https://www.youtube.com/) for detailed tutorials and walkthroughs!

---

## Feedback

We'd love to hear your thoughts! Your feedback helps us make Apiome better.

---

**Thank you for using Apiome!**

*Last updated: November 23, 2026*


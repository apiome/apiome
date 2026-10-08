# DEMONSTRATION — COL-EPIC-1: Comments & Threads

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [COL-EPIC-1 #4509](https://github.com/apiome/apiome/issues/4509) · umbrella [COL #4508](https://github.com/apiome/apiome/issues/4508) |
| Wave | 3 — the foundation of the collaboration lane |
| Tickets | [1.1 #4513](https://github.com/apiome/apiome/issues/4513) · [1.2 #4514](https://github.com/apiome/apiome/issues/4514) · [1.3 #4515](https://github.com/apiome/apiome/issues/4515) · [1.4 #4516](https://github.com/apiome/apiome/issues/4516) |
| Runtime | ~10 min, plus 10 min prep |
| Audience | teams whose API design discussion currently lives in Slack screenshots |
| The one beat | **The argument about the field is attached to the field — and it survives the rename.** |

> Record this with [COL-EPIC-2](DEMONSTRATION_EPIC_4510.md) and
> [COL-EPIC-3](DEMONSTRATION_EPIC_4511.md) in one session, same tenant, same project. They are
> three chapters of one story and the seeded data carries across.

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | Where the discussion lives today | A screenshot in Slack, with no link back. | 1:00 |
| 2 | Comment on the thing itself | Anchored to a property, not to a line number. | 2:30 |
| 3 | Mention someone | The person who needs to answer knows they do. | 1:30 |
| 4 | The Discussion panel | Every open thread in the project, in one list. | 2:00 |
| 5 | Rename the property | The thread follows it. This is the whole trick. | 2:00 |
| 6 | Delete it | The thread orphans visibly instead of vanishing. | 1:00 |

---

## PREP — before anyone is watching (~10 min)

**DO** — Start the stack.

```bash
yarn dev
```

**DO** — Import the petstore spec into a project. You need a schema with a property you are
willing to rename on camera — `Pet.tag` works.

**DO** — Have **two browser profiles** signed in as two different members of the same tenant.
Act 3's mention needs a real second person, and switching accounts mid-demo is slower than
switching windows. Add the second user to the tenant in prep, not on stage.

**DO** — Seed three or four existing threads across different elements so Act 4's panel has
something in it. An empty list does not demonstrate a list.

**DO** — Full dry run. Reset by deleting the project.

---

## ACT 1 — Where the discussion lives today (1:00)

**DO** — Open Studio at <http://localhost:3000/ade/studio/editor>. Show the schema.

**SAY**

> Here is how the conversation about this field happens today. Someone screenshots it, pastes it
> into Slack, and types "should this be nullable?"
>
> Three things go wrong, always. The thread is not attached to the field, so nobody finds it
> later. The decision is not attached to the field either, so in four months someone asks the
> same question. And when the field gets renamed, the screenshot becomes archaeology.
>
> None of that is a Slack problem. It's a *location* problem — the discussion is in a different
> system from the thing being discussed.

---

## ACT 2 — Comment on the thing itself (2:30)

**DO** — Hover the `tag` property row. A comment affordance appears. Click it.

**DO** — Type a real question — "Should this be nullable? The mobile client treats missing and
empty as the same thing." Post it.

**DO** — *Pause.* Show the unresolved-count badge appearing on the node header.

**DO** — Toggle **Comment mode** on the canvas. Show the badges across the diagram, and then
toggle it off to show the canvas decluttering again.

**SAY**

> The thread is on the property. Not on a line number, not on a file, not on a version — on the
> element.
>
> That distinction sounds pedantic until Act 5. A line-number anchor is broken by the next edit
> anyone makes above it. An element anchor is stable because the element has an identity of its
> own.
>
> And the badge is on the node, so someone opening this schema next week can see there is an open
> question without going looking for one. Comment mode turns the whole layer off when you want to
> just design.

---

## ACT 3 — Mention someone (1:30)

**DO** — Reply in the thread and type `@`. Show the autocomplete listing tenant members — and
only tenant members.

**DO** — Mention your second user. Post.

**DO** — Switch to the second browser profile. Show that the mention is visible to them.

**SAY**

> Mentions resolve against project membership, and they're parsed on the server — so what is
> stored is a real user reference, not a string that happens to start with an at-sign. That
> matters because the notification fan-out reads it, and because a mention of someone who has
> left the tenant should not silently address nobody.
>
> Right now the mention just sits there. In the third chapter of this story it becomes a
> notification.

---

## ACT 4 — The Discussion panel (2:00)

**DO** — Go to the project's **Discussion** tab.

**DO** — Show the filters: **Open**, **Resolved**, **Mentions me**, and by element type.

**DO** — Click **Mentions me** as the second user. Two threads.

**DO** — Click a thread. *Pause on the transition.* It deep-links into Studio with the element
focused and the popover already open.

**SAY**

> Anchoring to elements gives you the per-element view for free. This is the other view: every
> open question in the project, filterable, so "what is blocking this design" is a page rather
> than an archaeology exercise.
>
> And clicking through doesn't just open Studio — it opens Studio *at the element*, with the
> thread open. The round trip in both directions is the point. A discussion list you can't get
> back out of is just a second inbox.

---

## ACT 5 — Rename the property (2:00)

*The act that proves the design. Do not skip it, and do not rush it.*

**DO** — In Studio, rename `tag` to `category`. Save.

**DO** — *Pause.* The thread is still there, on the renamed property, with its full history.

**SAY**

> Rename the field, and the conversation about the field comes with it.
>
> That works because the anchor is the element's identifier — which is already the primary key —
> not its name and not its position. Nothing had to be migrated, re-matched or heuristically
> re-attached, because nothing about the anchor changed.
>
> This is the difference between a commenting feature that people trust and one they abandon.
> The moment a team loses a thread to a refactor, they go back to Slack — and they are right to,
> because a tool that drops your history under normal use is worse than no tool.

---

## ACT 6 — Delete it (1:00)

**DO** — Delete the `category` property.

**DO** — Open the Discussion panel. The thread is listed as **orphaned**, showing the last known
element label, with a **Relink** action.

**DO** — Relink it to a different property. It reattaches with its history.

**SAY**

> Deleting the element does not delete the conversation, and it does not leave a thread pointing
> into nothing.
>
> It orphans — visibly, with the label the element had when it died, and with a way to put it
> somewhere else. Because "we removed that field" is often the *answer* to the discussion, and
> that is exactly the record you would most regret losing.

---

## RESCUE — when it goes wrong on stage

**The comment affordance doesn't appear on hover**
Comment mode is off, or the element type isn't a supported anchor.
*On stage:* use the node header's comment action instead of the property row, and adjust the
narration to "on the model" rather than "on the property".

**Mention autocomplete is empty**
The second user isn't a member of *this* project's tenant.
*On stage:* skip the mention; post a plain reply. Fix membership before the COL-EPIC-3 recording,
which depends on it.

**The rename loses the thread**
This is a genuine failure of the epic's central claim. Do not talk past it.
*On stage:* stop the demo. File it. Act 5 is the reason this video exists.

**The deep link opens Studio but not the element**
Focus timing — the canvas mounted after the deep-link handler ran.
*On stage:* scroll to the element manually and move on; note it for the bug list.

---

## IF ASKED

**"Is it real-time? Do I see someone else's comment appear?"**
Threads round-trip without a reload, but live presence and co-editing are
[COL-EPIC-4](https://github.com/apiome/apiome/issues/4512) — deliberately v2. Presence before
review semantics would have been the wrong order.

**"Who can comment?"**
Anyone with project read access. Editing and deleting are limited to the author and admins, and
it is rate-limited — comments are a write path exposed to everyone who can read.

**"Can consumers of a published API comment?"**
Not in this epic. Portal consumer feedback is
[COL-4.4](https://github.com/apiome/apiome/issues/4528), and it needs the browse auth work first.

**"What about email?"**
[COL-3.3](https://github.com/apiome/apiome/issues/4523), `Future`. In-app notification is the
MVP; email needs the SMTP infrastructure from the OAuth roadmap.

---

## Reference

| Surface | Where |
|---|---|
| Studio editor | <http://localhost:3000/ade/studio/editor> |
| Project Discussion panel | project → **Discussion** tab |
| Projects | <http://localhost:3000/ade/dashboard/projects> |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_COLLABORATION_REVIEW.md` §3 |

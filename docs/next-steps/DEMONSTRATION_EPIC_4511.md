# DEMONSTRATION — COL-EPIC-3: Notifications

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [COL-EPIC-3 #4511](https://github.com/apiome/apiome/issues/4511) · umbrella [COL #4508](https://github.com/apiome/apiome/issues/4508) |
| Wave | 3 — closes the Collaboration MVP |
| Tickets | [3.1 #4521](https://github.com/apiome/apiome/issues/4521) · [3.2 #4522](https://github.com/apiome/apiome/issues/4522) |
| Builds on | COL-1.1 mentions ✅ · COL-2.1 review events ✅ (both Wave 3) |
| Runtime | ~5 min, plus 5 min prep |
| Audience | the same room as the previous two chapters |
| The one beat | **The person who has to act finds out without anyone remembering to tell them.** |

> This is a short chapter by design. **Record it as the tail of the
> [COL-EPIC-2 session](DEMONSTRATION_EPIC_4510.md)** — same tenant, same two profiles, same
> project. On its own it is a bell icon; after the review chapter it is the thing that makes the
> review chapter work.

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The gap | A review request nobody knows about is a blocked release. | 0:45 |
| 2 | The bell | Mention, review request, decision — all three arrive. | 2:00 |
| 3 | The full page | Grouped, filterable, and it survives being ignored. | 1:15 |
| 4 | Turn some off | Preferences, per type. | 1:00 |

---

## PREP — before anyone is watching (~5 min)

**DO** — Continue directly from the COL-EPIC-2 recording, or reproduce its end state: a project
with open threads, one review in flight, two signed-in profiles.

**DO** — Generate a **backlog** before recording — a mention, a review request, a decision, a
resolved thread. A notification center with one item in it demonstrates nothing; four items with
different types demonstrate grouping.

**DO** — Do *not* pre-read them. The unread badge is the first thing on screen.

---

## ACT 1 — The gap (0:45)

**DO** — As the author, show the review you requested in the previous chapter, still sitting at
"pending".

**SAY**

> Everything in the last two chapters assumed somebody looks. The thread with a question in it,
> the review waiting on a decision — both are inert until the right person notices.
>
> Which in practice means someone sends a Slack message saying "hey, can you look at this",
> and the whole record-keeping story we just built has a human ping holding it together.

---

## ACT 2 — The bell (2:00)

**DO** — Switch to the reviewer profile. *Pause on the header.* The bell carries an unread count.

**DO** — Open the dropdown. Show the entries, grouped by type — a mention, a review request, a
decision on something they commented on.

**DO** — Click the mention. It deep-links to the thread, with the element focused.

**DO** — Go back. Click the review request. It opens the review page.

**SAY**

> Mention, review request, decision. Each one lands where the thing actually is — not on a
> summary page that makes you go looking.
>
> These are written in the same transaction as the events that cause them. That is not an
> implementation detail you'd normally mention, but it's the difference between a notification
> system and a notification system people trust: a review request that commits while its
> notification silently fails is exactly the bug that teaches everyone to go back to Slack.

---

## ACT 3 — The full page (1:15)

**DO** — Click **See all** → <http://localhost:3000/ade/dashboard/notifications>.

**DO** — Show the grouping and the type filter. Click **Mark all read**. The badge clears.

**SAY**

> The dropdown is for the last few. This is for the Monday morning after a week off.
>
> Grouped by type, filterable, and — importantly — it has a retention cap. An unbounded activity
> log is a table that grows forever and a page nobody opens twice.

---

## ACT 4 — Turn some off (1:00)

**DO** — Open the per-type preferences. Turn off notifications for thread resolutions, leave
mentions and review requests on.

**DO** — As the author, resolve a thread the reviewer commented on. Show that no notification
arrives.

**DO** — Then request a review. It arrives.

**SAY**

> Per type, per user. Because the fastest way to make people ignore a notification system is to
> notify them about everything, and the second fastest is to make it all-or-nothing.
>
> That's the Collaboration MVP: the discussion is attached to the design, decisions are bound to
> what was decided, and the person who has to act finds out on their own. Email and Slack
> delivery are the next chapter — same fan-out, different transport.

---

## RESCUE — when it goes wrong on stage

**The badge doesn't update**
The unread count is polled and hasn't refreshed.
*On stage:* reload the page. Do not wait for a poll interval on camera.

**A notification links to the wrong element**
Deep-link format drift between the thread UI and the notification payload.
*On stage:* navigate manually, note the bug — the link format is shared with the Discussion
panel, so this is worth a real fix.

**No notifications at all**
The reviewer is not a member of the project, so no events fan out to them.
*On stage:* nothing quick. Verify membership in prep — this is the same prerequisite the mention
autocomplete needed in the first chapter.

---

## IF ASKED

**"Email? Slack?"**
[COL-3.3](https://github.com/apiome/apiome/issues/4523) and
[COL-3.4](https://github.com/apiome/apiome/issues/4524), both `Future`. The fan-out and the
preference model are built to carry them; email additionally needs the SMTP infrastructure from
the OAuth roadmap.

**"Will this notify me about my own actions?"**
No. Self-generated events are suppressed.

**"How long are they kept?"**
There is a retention cap, and it is per license tier — the same shape as the other retention
policies.

---

## Reference

| Surface | Where |
|---|---|
| Notification center | <http://localhost:3000/ade/dashboard/notifications> |
| Bell | ADE header, every dashboard route |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_COLLABORATION_REVIEW.md` §3 |

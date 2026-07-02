# Apiome 60–90 Second Demo Script

## High-level Flow

1. Open on Studio / dashboard and introduce the platform.
2. Create or open a simple "Orders API" project & version.
3. Use the visual canvas to add an enum and a reference between objects.
4. Flip to the generated OpenAPI spec view and highlight the changes.
5. Show the Swagger / live docs view for the "aha" moment.

---

## Spoken Script (60–90 seconds)

**[0–10s — Open on Studio / Dashboard]**

> On screen: Be on the main Studio view or project dashboard with a project list visible.

**You say:**  
"Let me show you Apiome in under a minute.

This is a visual OpenAPI workspace: instead of hand-editing YAML, you model your API as objects and relationships, 
and Apiome keeps your OpenAPI spec and Swagger docs perfectly in sync."

---

**[10–25s — Create or open a project & version]**

> On screen:  
> - Click **New Project** (or open an existing `Orders API` demo project).  
> - If new: type `Orders API`, version `1.0.0`, click **Create**.  
> - Land in the Studio for that project/version.

**You say:**  
"I’ll start with a simple project for an Orders API.

This gives me a versioned workspace where my schema, spec, and docs all come together."

---

**[25–50s — Visual modeling & “spec by doing”]**

> On screen:  
> - Show the canvas with a couple of nodes, e.g. `Order` and `Customer`.  
> - Click the **`Order`** node to open its properties panel.

**You say:**  
"Here on the canvas, each card is a schema object. Let’s tweak the `Order` model."

> On screen:  
> - Click **Add Property**.  
> - Name: `status`.  
> - Type: `string`.  
> - Mark it as an **enum** with values `NEW`, `SHIPPED`, `CANCELLED`.  
> - Toggle **Required** = on. Save.

**You say:**  
"I’ll add a `status` field as an enum so consumers know exactly which states are valid…"

> On screen:  
> - Add another property `customer`.  
> - Set type to **reference** and pick the existing `Customer` schema. Save.

**You say:**  
"…and link an `Order` to a `Customer` just by referencing the existing schema.

With these clicks, I’ve changed both my domain model and my OpenAPI schema—without touching a line of YAML."

---

**[50–70s — Flip to OpenAPI spec view]**

> On screen:  
> - Switch from **Canvas** to **Code / OpenAPI** view (the view toggle in the Studio).  
> - Scroll to `components.schemas.Order`.

**You say:**  
"Now watch what that did to the spec.

You can see `status` here as an enum, `customer` as a `$ref` to the `Customer` schema, and it’s marked as required.

This document is always generated from the model—no copying into separate repos, no stale definitions."

> Optional on screen:  
> - Click **Copy** or **Download** to show you can export the spec instantly.

**You say (optional):**  
"If I need to share this, I just copy or download the OpenAPI document directly from here."

---

**[70–90s — Swagger “aha” moment]**

> On screen:  
> - Switch from **Code** to **Swagger** view.  
> - Expand an endpoint or the `Order` schema.  
> - Point at the request/response models; highlight the `status` enum and `customer` ref.  
> - If a backend is wired up, optionally click **Try it out** on a simple operation and show a sample request.

**You say:**  
"And the best part is we don’t stop at the spec.

From the same source of truth, you get live Swagger docs. I can expand `Order` here and you’ll see the exact same 
`status` enum and `customer` reference reflected in the docs.

So in one place I have: visual modeling on the canvas, a clean OpenAPI spec, and interactive docs for API consumers.

That’s the ‘aha’: every change I make to the model instantly flows through to the spec and docs, so our teams stay
aligned and we never debug mismatched contracts again."

---

## Quick Checklist of Things to Show

- [ ] Start on a recognizable project view (e.g., `Orders API 1.0.0` Studio).  
- [ ] Show the **canvas** with a couple of nodes (`Order`, `Customer`).  
- [ ] Add a **new property with enum** to `Order` (`status` with 3 values, mark Required).  
- [ ] Add a **reference** property from `Order` → `Customer`.  
- [ ] Flip to the **Code/OpenAPI** view and scroll to `components.schemas.Order`.  
- [ ] Point out the generated `enum`, `required`, and `$ref`.  
- [ ] Click **Copy** or **Download** to show export.  
- [ ] Flip to the **Swagger** view; expand an endpoint or schema that uses `Order`.  
- [ ] (Optional) Use **Try it out** if `apiome-rest` is running.  
- [ ] Close with the “three synchronized views from one source of truth” message.

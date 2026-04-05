# Objectified: Collaboration - Feature Roadmap

> Real-time collaboration suite that enables teams to co-edit schemas simultaneously with live cursors, inline comments and discussions, PR-style review and approval workflows, and comprehensive team management—turning schema design from a solo activity into a multiplayer experience.
>
> **Revenue Model**: Team tier feature, enterprise collaboration add-ons
>
> **Tech Stack**: NextJS App Router, Radix UI primitives, WebSocket/Server-Sent Events, CRDT (Yjs), REST/OpenAPI 3.1, PostgreSQL, Redis (pub/sub)
>
> **Last Updated**: April 2, 2026

---

## MVP Definition

- WebSocket connection manager with automatic reconnection and room-based multiplexing
- Yjs CRDT document model for conflict-free simultaneous schema editing
- Live cursors showing each collaborator's position and selection on the canvas
- Presence indicators with user avatars, online/idle/offline status, and "N users viewing" badge
- Inline comment threads on schema classes, properties, and relationships with resolve/unresolve
- @mention support with in-app notification delivery
- Change request creation from draft edits with PR-style review lifecycle
- Side-by-side diff view comparing change request against the base schema version
- Configurable approval workflows with required reviewer count and merge gating
- Project teams with team-based permission scoping

---

## Epic 1: Real-Time Editing

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 1.1 (#1325) | WebSocket Infrastructure & Connection Manager | Room-based WebSocket server with Redis pub/sub fan-out and automatic reconnection | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | Yes |
| 1.2 (#1345) | CRDT Document Model (Yjs) | Yjs-backed document model for conflict-free concurrent schema editing | `ai-generated`, `enhancement`, `collaboration`, `mvp` | Yes |
| 1.3 (#1353) | Live Cursors & Selection Rendering | Render remote collaborator cursors and selections on the canvas in real time | `ai-generated`, `enhancement`, `collaboration`, `mvp` | No |
| 1.4 (#1358) | Presence Indicators & Idle Detection | User avatars, online/idle/offline status, and active viewer count | `ai-generated`, `enhancement`, `collaboration`, `mvp` | No |

### Detailed Issue Descriptions

---

#### 1.1 (#1325) — WebSocket Infrastructure & Connection Manager

The WebSocket infrastructure is the transport backbone for all real-time collaboration features. It provides a persistent, bidirectional channel between each connected client and the server, organized around the concept of "rooms" — one room per schema project. When a user opens a schema editor, the client joins the corresponding room and begins receiving updates from other participants.

The server runs a WebSocket upgrade handler at `app/api/v1/collaboration/ws/route.ts` (NextJS route handler delegating to a standalone WS process). Each room is backed by a Redis pub/sub channel, allowing horizontal scaling across multiple server instances. When a client publishes a message (cursor move, CRDT update, presence heartbeat), the server broadcasts it to the Redis channel, and all server instances fan it out to their locally connected clients in that room.

```
┌──────────┐    WS     ┌──────────────┐   Redis pub/sub   ┌──────────────┐    WS     ┌──────────┐
│ Client A │◄────────►│   Server 1   │◄──────────────────►│   Server 2   │◄────────►│ Client B │
└──────────┘           │  Room: proj-1│                    │  Room: proj-1│           └──────────┘
                       └──────────────┘                    └──────────────┘
┌──────────┐    WS           ▲                                   ▲           WS     ┌──────────┐
│ Client C │◄────────────────┘                                   └──────────────────►│ Client D │
└──────────┘                                                                         └──────────┘
```

The client-side connection manager handles automatic reconnection with exponential backoff (1s, 2s, 4s, capped at 30s), queues outgoing messages during disconnection, and replays them on reconnect. A connection status indicator in the editor toolbar (Radix UI `Badge`) shows "Connected," "Reconnecting...," or "Offline" with appropriate color coding. The manager also supports graceful degradation — if WebSocket is unavailable, it falls back to Server-Sent Events for read-only presence updates.

Authentication piggybacks on the existing session token. The WS handshake validates the token and extracts tenant/user context. Unauthorized connections are rejected with a 4001 close code. Rate limiting is applied per-connection (100 messages/second) to prevent abuse.

**Acceptance Criteria**
- WebSocket connections authenticate via existing session token during handshake
- Room-based multiplexing isolates messages to a single schema project
- Redis pub/sub enables horizontal scaling across multiple server instances
- Automatic reconnection with exponential backoff (1s → 30s cap) queues and replays missed messages
- Connection status badge shows Connected / Reconnecting / Offline in the editor toolbar
- Fallback to SSE for read-only presence when WebSocket is unavailable
- Rate limiting enforced at 100 messages/second per connection

**Part of Epic: Real-Time Editing**

---

#### 1.2 (#1345) — CRDT Document Model (Yjs)

The CRDT document model enables multiple users to edit the same schema simultaneously without conflicts. Yjs is used as the CRDT implementation — each schema project is represented as a Yjs `Y.Doc` containing shared types for the schema tree (classes, properties, relationships) and canvas layout (node positions, zoom level).

The Yjs document structure mirrors the Objectified schema model: a `Y.Map` at the root holds `classes` (a `Y.Array` of `Y.Map` entries), `properties` (nested under each class), and `relationships` (a `Y.Array` of edge definitions). When a user adds a property or moves a node, the corresponding Yjs operation is applied locally and synced to remote peers via the WebSocket room. Yjs's CRDT guarantees that all peers converge to the same state regardless of operation ordering.

Server-side persistence stores the Yjs document state as a binary blob in PostgreSQL (`collaboration_documents` table with a `yjs_state` BYTEA column). The server acts as a Yjs persistence provider — on room creation it loads the latest state from the database, and periodically snapshots the merged state back. This ensures that a user joining a room receives the full current state even if no other peers are connected.

```
┌─────────────────────────────────────────────────────┐
│  Y.Doc (Schema Project)                             │
│                                                     │
│  ├── classes: Y.Array                               │
│  │   ├── [0]: Y.Map { name, description, ... }      │
│  │   │   └── properties: Y.Array                    │
│  │   │       ├── [0]: Y.Map { name, type, ... }     │
│  │   │       └── [1]: Y.Map { name, type, ... }     │
│  │   └── [1]: Y.Map { name, description, ... }      │
│  │                                                   │
│  ├── relationships: Y.Array                          │
│  │   └── [0]: Y.Map { source, target, type }         │
│  │                                                   │
│  └── canvas: Y.Map                                   │
│      ├── positions: Y.Map { nodeId → {x, y} }       │
│      └── viewport: Y.Map { zoom, panX, panY }       │
└─────────────────────────────────────────────────────┘
```

Change attribution is tracked by tagging each Yjs update with the originating user ID. The attribution metadata enables "blame" functionality — hovering over a class or property shows who last modified it and when. Undo/redo is scoped per-user using Yjs's `UndoManager`, so undoing your own change never reverts someone else's work.

**Acceptance Criteria**
- Schema classes, properties, and relationships are modeled as Yjs shared types
- Concurrent edits from multiple users converge to the same state without data loss
- Server persists Yjs document state to PostgreSQL and loads it on room initialization
- Change attribution tags every update with the originating user ID
- Per-user undo/redo via Yjs UndoManager does not affect other users' changes
- Document state snapshots are taken every 30 seconds and on last-user-leave
- Yjs binary sync protocol is used over WebSocket for bandwidth efficiency

**Part of Epic: Real-Time Editing**

---

#### 1.3 (#1353) — Live Cursors & Selection Rendering

Live cursors let collaborators see exactly where each other user is working on the canvas. Each user's cursor position, selection range, and currently focused element are broadcast via the Yjs awareness protocol over the WebSocket room. Remote cursors render as colored arrows with the user's name label, using a deterministic color assignment per user.

The awareness state for each user includes: cursor position (x, y on canvas), selected element IDs (for multi-select), focused input field (for property editors), and a display name with avatar URL. Updates are throttled to 50ms intervals to balance responsiveness with bandwidth. Cursors that haven't moved for 5 seconds fade to 50% opacity; cursors from disconnected users are removed after a 2-second grace period.

On the canvas, remote cursors render as SVG overlays positioned above the node layer. In form-based editors (property panels, class dialogs), remote focus is indicated by a colored border on the active field with the user's name in a small Radix UI `Tooltip`. When two users select the same node, both selection rings are visible with distinct colors.

```
┌────────────────────────────────────────────────────────┐
│  ┌─ Alice (blue) ─────────────────────┐                │
│  │                                     │                │
│  │   ┌──────────┐     ┌──────────┐    │                │
│  │   │  User    │─────│  Order   │    │                │
│  │   │  Class   │     │  Class   │    │                │
│  │   └──────────┘     └────┬─────┘    │                │
│  └─────────────────────────┼──────────┘                │
│                            │                            │
│              ▲ Bob         │                            │
│              (green)  ┌────▼─────┐                      │
│                       │ Product  │ ◄── Carol (orange)   │
│                       │  Class   │                      │
│                       └──────────┘                      │
│                                                         │
│  [👤 Alice] [👤 Bob] [👤 Carol]   3 users viewing       │
└────────────────────────────────────────────────────────┘
```

Smooth animation is applied to remote cursor movement using CSS transitions (150ms ease-out) so cursors glide rather than teleport. When a remote user scrolls or pans to a different area of the canvas, their cursor disappears from the current viewport and a small directional indicator appears at the canvas edge pointing toward their location.

**Acceptance Criteria**
- Remote cursors render as colored arrows with the user's name label on the canvas
- Cursor positions update at 50ms throttle intervals with smooth CSS transitions
- Idle cursors (no movement for 5 seconds) fade to 50% opacity
- Disconnected user cursors are removed within 2 seconds of disconnect
- Remote selections render as colored rings around selected nodes
- In form editors, remote focus shows as a colored border with user name tooltip
- Off-screen remote users show directional indicators at the canvas edge

**Part of Epic: Real-Time Editing**

---

#### 1.4 (#1358) — Presence Indicators & Idle Detection

Presence indicators show who is currently viewing or editing a schema project. The presence bar in the editor header displays avatar stacks for active users, with overflow handled by a "+N" badge. Clicking the presence bar opens a Radix UI `Popover` listing all connected users with their status (active, idle, offline) and current location within the project (e.g., "Editing User class," "Viewing canvas").

Idle detection transitions a user from "active" to "idle" after 5 minutes of no mouse movement, keystrokes, or scroll events. The idle state is broadcast via the Yjs awareness protocol. Idle users' avatars dim to 50% opacity in the presence bar, and their cursors (from 1.3) fade further. Returning to the tab or moving the mouse transitions back to "active" immediately.

The presence state is also surfaced on the project list page (`app/(dashboard)/projects/page.tsx`) as a small badge on each project card showing the number of active users. This lets team members see at a glance which projects have active collaborators before opening them. The badge updates via a lightweight SSE endpoint that streams project-level presence counts.

REST endpoints support querying presence history: `GET /api/v1/collaboration/projects/{projectId}/presence` returns the current user list with statuses, and `GET /api/v1/collaboration/projects/{projectId}/presence/history?from={iso}&to={iso}` returns session logs for analytics (who was online when, total editing time per user).

**Acceptance Criteria**
- Presence bar displays avatar stacks for active users with "+N" overflow badge
- Clicking the presence bar opens a popover with user names, statuses, and locations
- Idle detection triggers after 5 minutes of inactivity; return-to-active is immediate
- Idle users' avatars dim to 50% opacity in the presence bar
- Project list page shows active user count badge per project via SSE
- Presence history API returns session logs with per-user editing time
- Presence state survives page refresh within a 10-second reconnection window

**Part of Epic: Real-Time Editing**

---

## Epic 2: Comments & Discussions

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 2.1 (#1381) | Inline Comment Threads | Threaded comments attached to schema classes, properties, and relationships | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | Yes |
| 2.2 (#1389) | Canvas Comment Pins | Drop comment pins at arbitrary positions on the canvas with node linking | `ai-generated`, `enhancement`, `collaboration`, `rest` | Yes |
| 2.3 (#1396) | @Mentions & Notification Routing | Mention teammates in comments with email and in-app notification delivery | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | No |
| 2.4 (#1404) | Rich Comment Editor & Reactions | Markdown editing, code snippets, image attachments, and emoji reactions | `ai-generated`, `enhancement`, `collaboration` | Yes |

### Detailed Issue Descriptions

---

#### 2.1 (#1381) — Inline Comment Threads

Inline comments attach discussion threads to specific schema elements — classes, properties, and relationships. Each thread is anchored to a target element by its ID and renders as a comment icon badge on the element. Clicking the badge opens a Radix UI `Popover` containing the thread: the original comment, chronological replies, and a reply input.

Threads follow a lifecycle: open → resolved → reopened. Resolving a thread collapses it visually (the badge turns from blue to gray) and hides it by default, though a "Show resolved" toggle reveals them. Any participant can resolve or reopen a thread. The resolve action records who resolved it and when.

The comment list panel at `app/(dashboard)/projects/[projectId]/comments/page.tsx` aggregates all threads for a project in a filterable, searchable list. Filters include status (open, resolved), author, date range, and target element type (class, property, relationship). Each list entry links back to the element on the canvas, scrolling and highlighting it.

REST endpoints: `POST /api/v1/collaboration/projects/{projectId}/comments` (create thread), `GET /api/v1/collaboration/projects/{projectId}/comments` (list with filters), `POST /api/v1/collaboration/projects/{projectId}/comments/{threadId}/replies` (reply), `PATCH /api/v1/collaboration/projects/{projectId}/comments/{threadId}` (resolve/reopen). The `comment_threads` table stores `project_id`, `target_type`, `target_id`, `status`, `created_by`, `created_at`. The `comment_replies` table stores `thread_id`, `body`, `author_id`, `created_at`.

**Acceptance Criteria**
- Comments can be attached to schema classes, properties, and relationships by element ID
- Comment badge renders on the target element; clicking opens the thread popover
- Threads support replies in chronological order with author attribution
- Threads can be resolved and reopened by any participant
- Resolved threads are visually collapsed with a "Show resolved" toggle
- Comment list page aggregates all project threads with status, author, and date filters
- Thread creation and replies are broadcast in real time to connected users via WebSocket

**Part of Epic: Comments & Discussions**

---

#### 2.2 (#1389) — Canvas Comment Pins

Canvas comment pins let users drop a discussion marker at any arbitrary position on the canvas, optionally linked to a nearby node. Pins are useful for spatial discussions like "this area is getting crowded, should we split these into a separate diagram" or "the relationship between these two classes needs rethinking."

Entering "comment mode" via a toolbar toggle (Radix UI `Toggle`) changes the cursor to a crosshair. Clicking the canvas creates a numbered pin at that position and opens a Radix UI `Dialog` for entering the comment body. If the click lands within a node's bounding box, the pin auto-links to that node and follows it when the node is dragged. Unlinked pins stay at their canvas coordinates.

Pins render as numbered circles (1, 2, 3...) with the author's avatar color. Hovering a pin shows a preview tooltip with the first line of the comment and reply count. Clicking opens the full thread in a side panel (Radix UI `Sheet`) rather than a popover, since canvas pins tend to spawn longer discussions. The side panel shows all pins for the project as a scrollable list, with the clicked pin scrolled into view and highlighted.

REST endpoints: `POST /api/v1/collaboration/projects/{projectId}/pins` (create pin with `{x, y, linkedNodeId?, body}`), `GET /api/v1/collaboration/projects/{projectId}/pins` (list), `PATCH /api/v1/collaboration/projects/{projectId}/pins/{pinId}` (update position or resolve), `DELETE /api/v1/collaboration/projects/{projectId}/pins/{pinId}`.

**Acceptance Criteria**
- Comment mode toggle switches cursor to crosshair for pin placement
- Pins placed within a node's bounding box auto-link and follow node movement
- Unlinked pins stay at fixed canvas coordinates
- Pins render as numbered circles with author color and hover preview
- Full thread opens in a side panel with all project pins listed
- Pins support the same resolve/reopen lifecycle as inline comments
- Pin creation broadcasts to all connected users in real time

**Part of Epic: Comments & Discussions**

---

#### 2.3 (#1396) — @Mentions & Notification Routing

@mentions let comment authors reference specific teammates, triggering targeted notifications. Typing `@` in any comment input opens a Radix UI `Popover` autocomplete listing project members, filtered as the user types. Selecting a user inserts a mention token rendered as a styled chip with the user's name.

Mentions trigger notifications through three channels: in-app (notification center bell icon), email (immediate for direct mentions, batched for thread replies), and browser push (if enabled). The notification payload includes the mentioning user, the comment snippet, and a deep link to the exact comment thread in context on the canvas.

```
┌─────────────────────────────────────────────────────┐
│  Comment Input                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │ Hey @al│                                        │ │
│  │        ┌─────────────────────┐                  │ │
│  │        │ 👤 Alice Chen       │                  │ │
│  │        │ 👤 Alan Rodriguez   │                  │ │
│  │        │ 👤 Alex Park        │                  │ │
│  │        └─────────────────────┘                  │ │
│  │                                                  │ │
│  └─────────────────────────────────────────────────┘ │
│                                         [Send]       │
└─────────────────────────────────────────────────────┘
```

The notification routing engine at the server processes mention events from the comment creation flow. REST endpoints: `GET /api/v1/collaboration/notifications` (list for current user, paginated), `PATCH /api/v1/collaboration/notifications/{id}/read` (mark read), `PATCH /api/v1/collaboration/notifications/read-all` (mark all read), `GET /api/v1/collaboration/notifications/unread-count` (badge count). The `notifications` table stores `user_id`, `type` (mention, reply, thread_update), `payload` (JSONB), `read_at`, `created_at`. Email delivery uses the existing email service with a `collaboration-mention` template.

**Acceptance Criteria**
- Typing `@` opens an autocomplete popover filtered to project members
- Selecting a user inserts a styled mention chip in the comment body
- Mentions trigger in-app, email, and browser push notifications
- Notification payload includes the mentioner, comment snippet, and deep link
- In-app notification bell shows unread count badge
- Notification list supports mark-read and mark-all-read actions
- Email notifications are sent immediately for direct mentions, batched hourly for replies

**Part of Epic: Comments & Discussions**

---

#### 2.4 (#1404) — Rich Comment Editor & Reactions

The rich comment editor upgrades the plain-text comment input to support Markdown formatting, inline code snippets, image/file attachments, and emoji reactions. This brings comment quality closer to GitHub-style discussions, making technical conversations more effective.

The editor uses a Radix UI `Toolbar` above the textarea with formatting buttons: bold, italic, code, link, bulleted list, and image upload. Markdown is rendered in the comment display using a sanitized Markdown renderer. Code blocks receive syntax highlighting for common languages (TypeScript, JSON, SQL). Image attachments are uploaded to object storage via `POST /api/v1/collaboration/uploads` and inserted as Markdown image references.

Emoji reactions (thumbs up, thumbs down, heart, eyes, rocket, party) are available on every comment and reply. Clicking a reaction button (Radix UI `ToggleGroup` rendered as small emoji pills below the comment) toggles the current user's reaction. Reaction counts are shown next to each emoji. Reactions serve as lightweight feedback that reduces the need for "+1" reply comments.

The editor also supports pasting images directly from the clipboard, which auto-uploads and inserts a reference. File attachments (non-image) render as download links with file name and size. A 10 MB per-file limit and 50 MB per-thread limit are enforced server-side.

**Acceptance Criteria**
- Comment editor supports Markdown with live preview on submit
- Formatting toolbar provides bold, italic, code, link, list, and image upload buttons
- Code blocks render with syntax highlighting for TypeScript, JSON, and SQL
- Images can be uploaded via button or clipboard paste (10 MB limit per file)
- Emoji reactions (6 types) can be toggled on any comment or reply
- Reaction counts update in real time for all connected users
- File attachments render as download links with name and size metadata

**Part of Epic: Comments & Discussions**

---

## Epic 3: Review & Approval Workflows

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 3.1 (#1431) | Change Request Creation & Lifecycle | PR-style change requests from draft schema edits with status tracking | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | Yes |
| 3.2 (#1437) | Side-by-Side Diff Viewer | Visual diff comparing change request schema against the base version | `ai-generated`, `enhancement`, `collaboration`, `mvp` | Yes |
| 3.3 (#1445) | Review Assignment & Review Tools | Assign reviewers, submit reviews with comments and suggestions | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | No |
| 3.4 (#1452) | Approval Workflows & Merge | Configurable approval rules with required reviewers and merge gating | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | No |

### Detailed Issue Descriptions

---

#### 3.1 (#1431) — Change Request Creation & Lifecycle

Change requests bring a PR-style workflow to schema design. Instead of editing the production schema directly, users create a change request that captures their modifications as a draft branch. The change request tracks what was added, modified, or removed and provides a structured review flow before changes are merged into the base schema.

Creating a change request starts from the editor. A user makes edits in "draft mode" (indicated by a Radix UI `Badge` in the toolbar showing "Draft — unsaved changes"). When ready, they click "Create Change Request," which opens a Radix UI `Dialog` collecting a title, description (Markdown), and optional reviewer assignments. The change request snapshots the current draft state and the base schema version, producing a diffable pair.

Change requests follow a lifecycle: `draft` → `open` → `in_review` → `approved` → `merged` (or `closed`). Transitions are gated by rules configured in 3.4. The change request detail page at `app/(dashboard)/projects/[projectId]/change-requests/[crId]/page.tsx` shows the title, description, status badge, author, reviewers, timeline of events, and links to the diff viewer (3.2).

```
  draft ──► open ──► in_review ──► approved ──► merged
              │         │              │
              │         │              └──► changes_requested ──► in_review
              │         │
              └─────────┴──────────────────► closed
```

REST endpoints: `POST /api/v1/collaboration/projects/{projectId}/change-requests` (create), `GET /api/v1/collaboration/projects/{projectId}/change-requests` (list), `GET /api/v1/collaboration/projects/{projectId}/change-requests/{crId}` (detail), `PATCH /api/v1/collaboration/projects/{projectId}/change-requests/{crId}` (update title/description), `POST /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/transition` with body `{ action: "open" | "close" | "merge" }`.

**Acceptance Criteria**
- Users can create a change request from draft edits with title and description
- Change request snapshots both the draft state and base schema version
- Lifecycle follows draft → open → in_review → approved → merged (or closed)
- Change request list page shows all CRs with status, author, and reviewer info
- Detail page renders title, description, status, timeline, and diff link
- Closed change requests preserve the snapshot for historical reference
- Change request events (creation, status transitions) are broadcast via WebSocket

**Part of Epic: Review & Approval Workflows**

---

#### 3.2 (#1437) — Side-by-Side Diff Viewer

The diff viewer renders a visual comparison between the change request's draft schema and the base version. It operates in two modes: a structural diff showing added/modified/removed schema elements in a tree view, and a canvas diff showing visual layout changes with color-coded overlays.

The structural diff at `app/(dashboard)/projects/[projectId]/change-requests/[crId]/diff/page.tsx` renders a split-pane layout with the base schema on the left and the draft on the right. Added classes and properties are highlighted green, removed elements red, and modified elements amber. Within modified elements, individual field changes are shown inline (e.g., property type changed from `string` to `number`).

```
┌─────────────────────────────┬─────────────────────────────┐
│  Base (v12)                 │  Change Request #7           │
│                             │                              │
│  ┌─ User                    │  ┌─ User                     │
│  │  ├ id: uuid              │  │  ├ id: uuid               │
│  │  ├ name: string          │  │  ├ name: string           │
│  │  ├ email: string         │  │  ├ email: string          │
│  │  └ role: string          │  │  ├ role: enum ◄── modified│
│  │                          │  │  └ avatar: string ◄── new │
│  ├─ Order                   │  ├─ Order                    │
│  │  ├ id: uuid              │  │  ├ id: uuid               │
│  │  ├ total: number         │  │  ├ total: number          │
│  │  └ status: string        │  │  └ status: string         │
│  │                          │  │                            │
│  └─ Product ◄── removed     │  └─ Subscription ◄── new     │
│     ├ sku: string           │     ├ plan: string           │
│     └ price: number         │     └ billing: enum          │
└─────────────────────────────┴─────────────────────────────┘
```

The canvas diff overlays both versions on the same canvas with color coding. A toggle (Radix UI `ToggleGroup`) switches between "Split," "Unified," and "Canvas" diff modes. Reviewers can click on any changed element to open a comment thread anchored to that specific change, enabling targeted feedback.

REST endpoint: `GET /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/diff` returns a structured diff payload with `added`, `modified`, `removed` arrays for classes, properties, and relationships.

**Acceptance Criteria**
- Split-pane view shows base schema on the left and draft on the right
- Added elements are green, removed are red, modified are amber with inline field diffs
- Canvas diff mode overlays both versions on a single canvas with color coding
- Toggle switches between Split, Unified, and Canvas diff modes
- Reviewers can click changed elements to open contextual comment threads
- Diff payload includes change type and before/after values for each modified field
- Synchronized scrolling in split-pane mode keeps both sides aligned

**Part of Epic: Review & Approval Workflows**

---

#### 3.3 (#1445) — Review Assignment & Review Tools

Review assignment lets change request authors request specific teammates to review their changes. Reviewers receive notifications and can submit structured reviews with one of three verdicts: approve, request changes, or comment only. Each review optionally includes line-level comments attached to specific elements in the diff.

The author assigns reviewers during CR creation or afterward via a Radix UI `Popover` with a searchable member list and multi-select checkboxes. Assigned reviewers appear as avatar chips on the CR detail page with their review status: pending (gray), approved (green), changes requested (red), or commented (blue). The CR timeline shows review submission events with the verdict and summary comment.

Reviewers interact with the diff viewer (3.2). A review toolbar at the bottom of the diff page provides the verdict selector (Radix UI `RadioGroup` with "Approve," "Request Changes," "Comment") and a summary text area. Submitting a review transitions the CR status automatically: if all required reviewers approve, the CR moves to `approved`; if any reviewer requests changes, it moves to `changes_requested`.

REST endpoints: `POST /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/reviewers` (assign), `DELETE /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/reviewers/{userId}` (unassign), `POST /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/reviews` (submit review with `{ verdict, summary, comments[] }`), `GET /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/reviews` (list reviews).

**Acceptance Criteria**
- Authors can assign one or more reviewers via a searchable member popover
- Assigned reviewers receive in-app and email notifications
- Reviewers submit reviews with a verdict (approve, request changes, comment)
- Review submission includes optional per-element comments attached to diff items
- CR status auto-transitions based on review verdicts and approval rules
- Reviewer avatars on the CR page show review status with color coding
- Review history is preserved in the CR timeline with verdict and summary

**Part of Epic: Review & Approval Workflows**

---

#### 3.4 (#1452) — Approval Workflows & Merge

Approval workflows define the rules governing when a change request can be merged. Project administrators configure approval policies via a settings page at `app/(dashboard)/projects/[projectId]/settings/approvals/page.tsx`. Policies support requiring a minimum number of approvals (e.g., 2 of 3 reviewers), requiring specific people (e.g., project owner must approve), auto-approving small changes (fewer than N elements modified), and escalation on timeout (auto-notify admins after N days without review).

The merge action is gated by the approval policy. When all requirements are satisfied, the "Merge" button on the CR detail page becomes enabled. Merging applies the draft schema changes to the base schema, creating a new schema version. The merge operation is atomic — if the base schema has changed since the CR was created, a conflict check runs first. Conflicting changes surface a merge conflict dialog listing the conflicting elements, requiring manual resolution before merge.

```
┌────────────────────────────────────────────────────┐
│  Approval Policy: "schema-reviews"                  │
│                                                     │
│  ☑ Require 2 approvals minimum                     │
│  ☑ Require project owner approval                  │
│  ☐ Auto-approve changes touching < 3 elements      │
│  ☑ Escalate after 3 days without review            │
│                                                     │
│  Admin override: Enabled (with audit log entry)    │
│                               [Save Policy]         │
└────────────────────────────────────────────────────┘
```

Admin override allows a project administrator to force-merge a CR that hasn't met all approval requirements, with the override recorded in the audit trail. Post-merge, the CR status transitions to `merged`, the draft branch is archived, and all subscribers receive a notification with a summary of merged changes.

REST endpoints: `GET /api/v1/collaboration/projects/{projectId}/approval-policy` (current policy), `PUT /api/v1/collaboration/projects/{projectId}/approval-policy` (update), `POST /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/merge` (merge with optional `{ force: true }` for admin override), `GET /api/v1/collaboration/projects/{projectId}/change-requests/{crId}/merge-check` (pre-merge conflict check).

**Acceptance Criteria**
- Approval policies support minimum approval count and required-person rules
- Auto-approve rule skips review for changes below a configurable element threshold
- Escalation notifies admins after a configurable number of days without review
- Merge button is disabled until all approval requirements are satisfied
- Merge applies draft changes atomically and creates a new schema version
- Conflict detection runs before merge and surfaces conflicting elements for resolution
- Admin override force-merges with an audit trail entry
- Post-merge notifications are sent to all CR subscribers

**Part of Epic: Review & Approval Workflows**

---

## Epic 4: Team Management & Activity

### Summary Table

| #   | Title | Description | Labels | Parallel |
|-----|-------|-------------|--------|----------|
| 4.1 (#1475) | Project Teams & Team-Based Permissions | Create teams within tenants, assign to projects, scope permissions by team | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | Yes |
| 4.2 (#1476) | Activity Feeds & History | Per-project activity stream with filtering, search, and notification subscriptions | `ai-generated`, `enhancement`, `collaboration`, `rest` | Yes |
| 4.3 (#1481) | Notification Center & Preferences | Centralized notification hub with per-channel, per-project preference controls | `ai-generated`, `enhancement`, `collaboration`, `mvp`, `rest` | Yes |
| 4.4 (#1484) | External Integrations (Slack & Teams) | Push activity feed events to Slack and Microsoft Teams channels | `ai-generated`, `enhancement`, `collaboration`, `rest` | Yes |

### Detailed Issue Descriptions

---

#### 4.1 (#1475) — Project Teams & Team-Based Permissions

Project teams group users within a tenant for permission scoping and collaborative workflows. A team has a name, description, avatar, and a member list with per-member roles (team admin, member). Teams are assigned to projects with a project-level role (owner, editor, viewer, commenter) that determines what actions team members can perform.

The team management page at `app/(dashboard)/settings/teams/page.tsx` lists all teams for the tenant in a Radix UI `Table`. Creating a team opens a Radix UI `Dialog` with fields for name, description, and an initial member selector (Radix UI `Popover` with checkbox list). The team detail page shows members, assigned projects, and a team activity summary.

Permission resolution follows a precedence chain: explicit user-level project permission > team-level project permission > tenant-level default. When a user belongs to multiple teams assigned to the same project, the highest-privilege role wins. The permission check middleware evaluates this chain on every API request, caching resolved permissions in Redis with a 5-minute TTL.

REST endpoints: `POST /api/v1/collaboration/teams` (create), `GET /api/v1/collaboration/teams` (list), `PATCH /api/v1/collaboration/teams/{teamId}` (update), `DELETE /api/v1/collaboration/teams/{teamId}`, `POST /api/v1/collaboration/teams/{teamId}/members` (add member), `DELETE /api/v1/collaboration/teams/{teamId}/members/{userId}` (remove), `POST /api/v1/collaboration/projects/{projectId}/team-assignments` (assign team to project with role), `DELETE /api/v1/collaboration/projects/{projectId}/team-assignments/{teamId}`.

**Acceptance Criteria**
- Teams can be created with name, description, and initial member list
- Team members have roles (team admin, member) controlling team management permissions
- Teams are assigned to projects with a project-level role (owner, editor, viewer, commenter)
- Permission resolution follows user > team > tenant precedence with highest-privilege wins
- Resolved permissions are cached in Redis with 5-minute TTL and invalidated on role changes
- Team management page lists teams with member count and assigned project count
- Deleting a team revokes all team-based project permissions with a confirmation dialog

**Part of Epic: Team Management & Activity**

---

#### 4.2 (#1476) — Activity Feeds & History

Activity feeds provide a chronological stream of events for each project: schema edits, comment threads, change request lifecycle events, team membership changes, and permission updates. The feed serves as a project changelog that keeps the entire team informed without requiring everyone to be online simultaneously.

The activity feed page at `app/(dashboard)/projects/[projectId]/activity/page.tsx` renders events in a vertical timeline. Each event card shows the actor (avatar + name), action description, target element, and timestamp. Events are grouped by day with date headers. A filter sidebar (Radix UI `Checkbox` group) lets users narrow by event type (edits, comments, reviews, admin). A search bar performs full-text search over event descriptions.

Events are stored in an `activity_events` table with `project_id`, `actor_id`, `event_type`, `target_type`, `target_id`, `description`, `metadata` (JSONB), and `created_at`. The table is append-only and partitioned by month. Events are generated by a server-side event emitter that hooks into schema save, comment creation, CR lifecycle, and team management operations.

Users can subscribe to activity notifications for specific projects or event types. Subscriptions are managed via a Radix UI `DropdownMenu` on the feed page ("Subscribe to all," "Schema changes only," "Comments only," "Unsubscribe"). Subscribed events are delivered through the notification center (4.3). An RSS feed endpoint at `GET /api/v1/collaboration/projects/{projectId}/activity/rss` enables external feed reader integration.

**Acceptance Criteria**
- Activity feed displays project events in a chronological timeline grouped by day
- Events cover schema edits, comments, change requests, and team changes
- Filters narrow the feed by event type; search performs full-text matching on descriptions
- Users can subscribe to project activity notifications by event type
- RSS feed endpoint enables external feed reader integration
- Activity events are append-only and partitioned by month for query performance
- Feed loads initial page in under 500ms and supports infinite scroll for history

**Part of Epic: Team Management & Activity**

---

#### 4.3 (#1481) — Notification Center & Preferences

The notification center consolidates all collaboration notifications into a single hub accessible from the global header bell icon. A Radix UI `Popover` dropdown shows the latest unread notifications with a "View all" link to the full notification page at `app/(dashboard)/notifications/page.tsx`. Each notification entry displays the source (comment, mention, review request, CR status change), a brief message, and a timestamp. Clicking a notification navigates to the source and marks it as read.

Notification preferences are configured per-channel (in-app, email, browser push) and per-event-type (mentions, comment replies, review requests, CR merged, team invites). The preferences page at `app/(dashboard)/settings/notifications/page.tsx` renders a matrix of checkboxes using Radix UI `Checkbox` components. A "quiet hours" setting suppresses non-critical notifications during configured time windows. Email notifications support digest mode (immediate, hourly, daily) configurable per event type.

```
┌──────────────────────────────────────────────────────────────┐
│  Notification Preferences                                     │
│                                                               │
│             │ In-App │ Email        │ Browser Push │           │
│  ───────────┼────────┼─────────────┼──────────────┤           │
│  @Mentions  │  ☑     │ ☑ Immediate │     ☑        │           │
│  Replies    │  ☑     │ ☑ Hourly    │     ☐        │           │
│  Reviews    │  ☑     │ ☑ Immediate │     ☑        │           │
│  CR Merged  │  ☑     │ ☑ Daily     │     ☐        │           │
│  Team Inv.  │  ☑     │ ☑ Immediate │     ☐        │           │
│                                                               │
│  Quiet Hours: 10:00 PM — 7:00 AM  [Edit]                     │
└──────────────────────────────────────────────────────────────┘
```

REST endpoints: `GET /api/v1/collaboration/notifications` (paginated list), `PATCH /api/v1/collaboration/notifications/{id}/read`, `PATCH /api/v1/collaboration/notifications/read-all`, `GET /api/v1/collaboration/notifications/unread-count`, `GET /api/v1/collaboration/notification-preferences` (current prefs), `PUT /api/v1/collaboration/notification-preferences` (update). Browser push registration uses the Web Push API with VAPID keys stored server-side.

**Acceptance Criteria**
- Bell icon in the global header shows unread notification count badge
- Notification popover lists recent unread notifications with source and timestamp
- Clicking a notification navigates to the source context and marks it as read
- Preferences page renders a channel × event-type matrix with per-cell checkboxes
- Email digest mode supports immediate, hourly, and daily options per event type
- Quiet hours suppress non-critical notifications during configured time windows
- Browser push notifications use the Web Push API with opt-in permission flow

**Part of Epic: Team Management & Activity**

---

#### 4.4 (#1484) — External Integrations (Slack & Teams)

External integrations push collaboration activity to Slack and Microsoft Teams channels, keeping teammates informed in the tools they already use. Each project can be connected to one or more external channels. When a configured event type occurs (schema change, comment, CR status change, review requested), a formatted message is posted to the linked channel.

The integration setup page at `app/(dashboard)/projects/[projectId]/settings/integrations/page.tsx` guides users through the OAuth flow for Slack or Teams. After authorizing, users select the target channel from a Radix UI `Select` dropdown populated by the respective API. Event type filters (Radix UI `Checkbox` group) control which events are forwarded. A "Test" button sends a sample message to verify the integration.

Messages are formatted with the platform's rich message syntax: Slack Block Kit for Slack, Adaptive Cards for Teams. Each message includes the actor, action summary, a link back to Objectified, and contextual details (e.g., for a CR merge, the number of changed elements and the list of reviewers who approved).

REST endpoints: `POST /api/v1/collaboration/integrations/slack/connect` (initiate OAuth), `POST /api/v1/collaboration/integrations/teams/connect` (initiate OAuth), `GET /api/v1/collaboration/projects/{projectId}/integrations` (list active integrations), `PUT /api/v1/collaboration/projects/{projectId}/integrations/{integrationId}` (update event filters), `DELETE /api/v1/collaboration/projects/{projectId}/integrations/{integrationId}` (disconnect), `POST /api/v1/collaboration/projects/{projectId}/integrations/{integrationId}/test` (send test message).

**Acceptance Criteria**
- Slack and Microsoft Teams integrations connect via standard OAuth flows
- Channel selector lists available channels from the connected workspace
- Event type filters control which events are posted to the channel
- Messages use Slack Block Kit and Teams Adaptive Cards for rich formatting
- Each message includes actor, action, deep link, and contextual details
- Test button sends a sample message to verify the integration
- Disconnecting an integration stops all event delivery immediately

**Part of Epic: Team Management & Activity**

---

## Parallel Work Guide

**Epic 1 — Real-Time Editing**:
Issues 1.1 (WebSocket Infrastructure) and 1.2 (CRDT Document Model) can be developed in parallel — the WebSocket transport and the CRDT logic are independent layers that integrate through a thin sync adapter. Issue 1.3 (Live Cursors) depends on 1.1 for the WebSocket room and 1.2 for the Yjs awareness protocol. Issue 1.4 (Presence Indicators) depends on 1.1 and shares awareness state with 1.3, so it should follow 1.3 or be co-developed.

**Epic 2 — Comments & Discussions**:
Issues 2.1 (Inline Comments) and 2.2 (Canvas Pins) can be developed in parallel as they use independent data models and UI patterns. Issue 2.3 (@Mentions) depends on 2.1 since mentions live inside comment bodies. Issue 2.4 (Rich Editor & Reactions) can be developed in parallel with 2.1/2.2 since the editor component is self-contained and slots into both comment types.

**Epic 3 — Review & Approval Workflows**:
Issues 3.1 (Change Request Lifecycle) and 3.2 (Diff Viewer) can be built in parallel — the CR data model and the diff rendering are independent. Issue 3.3 (Review Assignment) depends on 3.1 for the CR entity and 3.2 for the review interface. Issue 3.4 (Approval Workflows & Merge) depends on 3.3 for review verdicts that feed the approval engine.

**Epic 4 — Team Management & Activity**:
All four issues (4.1, 4.2, 4.3, 4.4) can be developed in parallel. Teams (4.1) and activity feeds (4.2) operate on independent data models. The notification center (4.3) can be built against a mock event source initially. External integrations (4.4) use independent OAuth flows and message formatting.

**Cross-Epic Parallelism**:
Epic 1 (Real-Time Editing) is the foundational layer — other epics benefit from it but do not strictly depend on it for initial development. Epic 2 (Comments) can be built with REST-only delivery initially, then upgraded to real-time via Epic 1's WebSocket infrastructure. Epic 3 (Review & Approval) is fully independent of Epics 1 and 2. Epic 4 (Team Management) provides the user/team model consumed by all other epics, so 4.1 (Teams) should be prioritized early. The notification center (4.3) is a cross-cutting concern that integrates with comments (Epic 2) and reviews (Epic 3), but can be built with a generic event interface that each epic plugs into.

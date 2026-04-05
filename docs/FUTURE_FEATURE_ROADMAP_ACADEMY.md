# Objectified: Academy - Feature Roadmap

> A comprehensive learning management system (LMS) built around schema design, API development, and data architecture best practices. Academy transforms Objectified's domain expertise into structured, gamified learning experiences with certification programs and enterprise training packages.
>
> **Revenue Model**: Subscription tiers (Free/Pro/Enterprise), certification exam fees, enterprise training packages with custom curricula
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, S3-compatible media storage, OpenAPI 3.1, Ollama for AI-powered content suggestions

---

## MVP Definition

- Course catalog with browsable, filterable course listings
- Course CRUD (create, edit, publish courses with lessons and modules)
- Rich content editor for lesson authoring (text, code blocks, embedded media)
- Student enrollment and progress tracking with completion percentages
- Basic quiz/assessment engine for knowledge checks within lessons
- Badge and achievement system for gamified learning milestones
- User dashboard showing enrolled courses, progress, and earned badges
- REST API for all course and enrollment operations (OpenAPI 3.1 documented)

---

## Epic 1: Course Management Platform

### Summary Table

| #   | Title                              | Description                                                                 | Labels                                  | Parallel |
|-----|------------------------------------|-----------------------------------------------------------------------------|-----------------------------------------|----------|
| 1.1 (#882) | Course & Module Data Model         | Design database schema for courses, modules, lessons, and media assets      | `enhancement`, `mvp`, `academy`, `rest` | Yes      |
| 1.2 (#883) | Course CRUD REST API               | Implement REST endpoints for full course lifecycle management               | `enhancement`, `mvp`, `academy`, `rest` | No       |
| 1.3 (#884) | Rich Content Editor                | Build lesson authoring editor with markdown, code blocks, and media embeds  | `enhancement`, `mvp`, `academy`         | Yes      |
| 1.4 (#885) | Media Upload & Storage Pipeline    | S3-compatible upload pipeline for video, images, and downloadable assets    | `enhancement`, `mvp`, `academy`, `rest` | Yes      |
| 1.5 (#886) | Course Catalog & Discovery UI      | Browsable, filterable catalog page with search, tags, and difficulty levels  | `enhancement`, `mvp`, `academy`         | No       |
| 1.6 (#887) | Course Publishing Workflow         | Draft/review/publish state machine with preview and scheduling              | `enhancement`, `academy`, `rest`        | No       |

### Detailed Issue Descriptions

#### 1.1 (#882) — Course & Module Data Model

The foundation of Academy requires a well-structured relational data model that captures the hierarchy of learning content: courses contain modules, modules contain lessons, and lessons contain content blocks. Each entity needs metadata for discovery (tags, difficulty level, estimated duration), audit fields (created_by, updated_at), and tenant scoping for multi-tenant isolation.

The schema must support flexible ordering of modules within a course and lessons within a module via a `sort_order` integer field. Courses carry top-level metadata including a cover image URL, description, prerequisite course references, and a status enum (draft, in_review, published, archived). Lessons store their content as structured JSON to support the rich content editor, with a `content_type` discriminator for different block types (text, code, video, quiz).

A separate `course_tag` junction table enables many-to-many tagging for discovery. The `course_prerequisite` self-referential table enforces learning paths. All tables must include `tenant_id` for multi-tenant isolation and standard audit columns.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   course     │────▶│   module     │────▶│   lesson     │
├──────────────┤     ├──────────────┤     ├──────────────┤
│ id           │     │ id           │     │ id           │
│ tenant_id    │     │ course_id    │     │ module_id    │
│ title        │     │ title        │     │ title        │
│ description  │     │ description  │     │ content_json │
│ cover_image  │     │ sort_order   │     │ sort_order   │
│ difficulty   │     │ created_at   │     │ duration_min │
│ est_duration │     │ updated_at   │     │ content_type │
│ status       │     └──────────────┘     │ created_at   │
│ created_by   │                          └──────────────┘
│ created_at   │     ┌──────────────┐
│ updated_at   │     │ course_tag   │
└──────────────┘────▶├──────────────┤
                     │ course_id    │
                     │ tag_id       │
                     └──────────────┘
```

**Acceptance Criteria:**
- Database migration creates all tables with proper foreign keys, indexes, and constraints
- `course.status` uses a PostgreSQL enum with values: `draft`, `in_review`, `published`, `archived`
- `sort_order` fields default to 0 and support reordering without gaps
- All tables include `tenant_id` with a composite index on `(tenant_id, id)`
- JSON Schema validation exists for `lesson.content_json` structure
- Seed script populates sample course data for development

**Tech Stack:** PostgreSQL migrations, JSON Schema validation for content blocks, OpenAPI 3.1 component schemas for all entities

Part of Epic: Course Management Platform

---

#### 1.2 (#883) — Course CRUD REST API

Implement the full set of REST endpoints for managing courses, modules, and lessons. The API follows RESTful conventions with nested resource paths: `/api/v1/academy/courses`, `/api/v1/academy/courses/{courseId}/modules`, and `/api/v1/academy/courses/{courseId}/modules/{moduleId}/lessons`. All endpoints require authentication and enforce tenant isolation through middleware.

Bulk operations are essential for course authoring efficiency. The API must support bulk reordering of modules within a course (PATCH to `/courses/{id}/modules/reorder` with an ordered array of module IDs) and bulk reordering of lessons within a module. Pagination follows cursor-based patterns consistent with the rest of the Objectified API, returning `next_cursor` and `has_more` fields.

The API must validate all inputs against OpenAPI 3.1 schemas before persisting. Error responses follow RFC 7807 Problem Details format with field-level validation errors. Rate limiting applies per tenant with configurable limits.

**Acceptance Criteria:**
- Full CRUD endpoints for courses, modules, and lessons with OpenAPI 3.1 spec
- Nested resource URLs follow `/api/v1/academy/courses/{id}/modules/{id}/lessons` pattern
- Bulk reorder endpoints accept an array of IDs and update `sort_order` atomically
- Cursor-based pagination on list endpoints with configurable page size (default 20, max 100)
- All responses include standard envelope with `data`, `meta`, and `errors` fields
- 401/403 responses for unauthenticated/unauthorized access with tenant isolation enforced

**Tech Stack:** NextJS API routes (`app/api/v1/academy/...`), PostgreSQL queries, OpenAPI 3.1 spec generation, RFC 7807 error responses

Part of Epic: Course Management Platform

---

#### 1.3 (#884) — Rich Content Editor

Build a lesson content editor that enables course authors to create engaging learning materials using a block-based approach. Each lesson is composed of ordered content blocks: rich text (markdown with live preview), code snippets (with syntax highlighting and language selector), embedded media (video player, images with captions), interactive quiz questions (inline knowledge checks), and callout boxes (tip, warning, info).

The editor UI uses a vertical block list where authors can add, remove, reorder (drag-and-drop), and edit individual blocks. The toolbar provides block-type insertion buttons and formatting controls for the active block. A split-pane preview mode shows the rendered lesson alongside the editor for real-time feedback.

Content is persisted as a JSON array of typed block objects, enabling flexible rendering on the student-facing side without coupling to the editor implementation. The editor should handle auto-save with debounced persistence (every 3 seconds of inactivity) and explicit save with keyboard shortcut (Ctrl/Cmd+S).

**Acceptance Criteria:**
- Block types supported: `text` (markdown), `code` (with language selector), `media` (image/video embed), `quiz` (inline question), `callout` (tip/warning/info)
- Drag-and-drop reordering of blocks using accessible keyboard controls
- Split-pane editor/preview mode toggled via Radix UI Tabs component
- Auto-save with debounce (3s) and manual save (Ctrl+S) with visual save indicator
- Content serialized as JSON array of `{ type, data, sort_order }` block objects
- Editor loads existing lesson content and preserves block order on save

**Tech Stack:** NextJS page (`app/(platform)/academy/courses/[courseId]/modules/[moduleId]/lessons/[lessonId]/edit/page.tsx`), Radix UI Tabs for editor/preview toggle, Radix UI DropdownMenu for block type insertion, CodeMirror or Monaco for code blocks

Part of Epic: Course Management Platform

---

#### 1.4 (#885) — Media Upload & Storage Pipeline

Course content requires reliable media upload for video tutorials, images, diagrams, and downloadable assets (PDFs, code samples). The upload pipeline uses presigned URLs for direct-to-S3 uploads, bypassing the application server for large files. A background worker processes uploads: generating video thumbnails, transcoding video to HLS for adaptive streaming, creating image thumbnails at multiple resolutions, and extracting video duration metadata.

The media asset registry tracks all uploaded files with metadata: original filename, MIME type, file size, storage path, processing status (pending, processing, ready, failed), and associations to courses/lessons. A media library UI allows authors to browse, search, and reuse assets across courses.

Upload validation enforces file type restrictions (video: mp4/webm, image: png/jpg/webp/gif, documents: pdf), maximum file sizes (video: 2GB, image: 50MB, documents: 100MB), and virus scanning before marking assets as ready.

**Acceptance Criteria:**
- Presigned URL generation endpoint returns upload URL and asset ID for direct S3 upload
- Background worker processes uploads: video thumbnails, HLS transcoding, image resizing
- Media asset registry tracks upload status with polling endpoint for processing progress
- File type and size validation enforced server-side before presigned URL generation
- Media library UI with grid/list view, search by filename, and filter by type
- Orphaned asset cleanup job removes unattached uploads older than 24 hours

**Tech Stack:** NextJS API route for presigned URL generation, S3-compatible storage (MinIO for self-hosted), background worker for media processing, REST endpoint `POST /api/v1/academy/media/upload-url`

Part of Epic: Course Management Platform

---

#### 1.5 (#886) — Course Catalog & Discovery UI

The public-facing course catalog is the primary entry point for learners discovering Academy content. The catalog page displays courses in a responsive grid layout with cover images, titles, difficulty badges, estimated duration, enrollment count, and average rating. Filtering supports multiple dimensions: difficulty level (beginner/intermediate/advanced), tags/categories, duration range, and content type (video-heavy, hands-on labs, reading).

Search is powered by full-text search across course titles, descriptions, and tag names with result highlighting. Sort options include: newest, most popular (by enrollment count), highest rated, and shortest duration. Each course card links to a detail page showing the full syllabus (module and lesson list), prerequisites, instructor info, and an enrollment CTA.

The catalog must be performant with server-side rendering for SEO and fast initial loads. Pagination uses infinite scroll with a "Load more" trigger rather than traditional page numbers.

**Acceptance Criteria:**
- Responsive grid layout with course cards showing cover image, title, difficulty, duration, and enrollment count
- Filter panel using Radix UI Checkbox groups for difficulty and tags, with URL query parameter sync
- Full-text search with debounced input (300ms) and result highlighting
- Sort dropdown using Radix UI Select with options: newest, popular, highest rated, shortest
- Course detail page with syllabus tree, prerequisites, and enrollment button
- Server-side rendered with NextJS for SEO; infinite scroll pagination

**Tech Stack:** NextJS page (`app/(platform)/academy/catalog/page.tsx`), Radix UI Select for sort, Radix UI Checkbox for filters, PostgreSQL full-text search with `tsvector`

Part of Epic: Course Management Platform

---

#### 1.6 (#887) — Course Publishing Workflow

Courses follow a state machine lifecycle: Draft → In Review → Published → Archived. Authors create and edit courses in Draft state. When ready, they submit for review, which transitions the course to In Review. Reviewers (users with the `academy_reviewer` role) can approve (→ Published) or reject with feedback (→ Draft with review notes). Published courses can be archived, removing them from the catalog but preserving enrollment data.

The workflow includes a scheduled publish feature: authors can set a future publish date, and a background job transitions approved courses to Published at the scheduled time. A course preview mode allows reviewers and authors to see the full student experience before publishing.

Notifications are sent at each state transition: authors receive notifications on approval/rejection, reviewers receive notifications when courses are submitted. The review interface shows a diff of changes since the last published version for iterative updates.

**Acceptance Criteria:**
- State machine enforced at the API level with valid transitions: draft→in_review, in_review→published, in_review→draft (reject), published→archived
- Review submission requires all modules to have at least one lesson (validation)
- Reviewer role check on approve/reject endpoints with rejection reason (required text field)
- Scheduled publish stores `scheduled_publish_at` timestamp; background job processes queue every minute
- Preview mode renders course exactly as students see it, accessible via `/academy/courses/{id}/preview`
- State transition audit log records actor, timestamp, previous state, new state, and optional notes

**Tech Stack:** NextJS API routes for state transitions, Radix UI Dialog for review submission/rejection modals, Radix UI AlertDialog for archive confirmation, background job scheduler

Part of Epic: Course Management Platform

---

## Epic 2: Student Experience & Gamification

### Summary Table

| #   | Title                              | Description                                                                   | Labels                                  | Parallel |
|-----|------------------------------------|-------------------------------------------------------------------------------|-----------------------------------------|----------|
| 2.1 (#889) | Student Enrollment System          | Enrollment flow with seat management, waitlists, and enrollment history       | `enhancement`, `mvp`, `academy`, `rest` | Yes      |
| 2.2 (#890) | Progress Tracking Engine           | Lesson completion, module progress, course completion with percentage tracking | `enhancement`, `mvp`, `academy`, `rest` | No       |
| 2.3 (#891) | Student Dashboard                  | Personalized dashboard showing enrollments, progress, recommendations         | `enhancement`, `mvp`, `academy`         | No       |
| 2.4 (#892) | Badge & Achievement System         | Configurable badges awarded on milestones with display and sharing            | `enhancement`, `mvp`, `academy`, `rest` | Yes      |
| 2.5 (#893) | Leaderboards & Social Learning     | Tenant-scoped leaderboards with points, streaks, and peer comparisons         | `enhancement`, `academy`                | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#889) — Student Enrollment System

The enrollment system manages the relationship between students and courses. When a student enrolls, the system creates an `enrollment` record capturing the student ID, course ID, enrollment date, and status (active, completed, dropped, expired). For enterprise tenants, courses may have seat limits, requiring a waitlist mechanism that automatically enrolls the next student when a seat opens.

Enrollment validation checks prerequisites: if a course requires completion of another course, the system verifies the student has a completed enrollment for the prerequisite. Enrollment also triggers the creation of initial progress tracking records for all modules and lessons in the course, set to "not started."

The enrollment API supports bulk enrollment for enterprise training managers who need to assign courses to teams. A `POST /api/v1/academy/enrollments/bulk` endpoint accepts an array of user IDs and a course ID, validates prerequisites and seat availability for each, and returns per-user success/failure results.

**Acceptance Criteria:**
- `POST /api/v1/academy/enrollments` creates enrollment with prerequisite validation
- Seat limit enforcement returns 409 Conflict when course is full, with waitlist opt-in
- Waitlist auto-promotion triggers enrollment when seats become available (via drop or seat increase)
- Bulk enrollment endpoint processes up to 100 users per request with per-user error reporting
- Enrollment status transitions: `active` → `completed` | `dropped` | `expired`
- Enrollment history queryable via `GET /api/v1/academy/enrollments?userId={id}` with pagination

**Tech Stack:** NextJS API routes, PostgreSQL with row-level locking for seat management, OpenAPI 3.1 spec for enrollment endpoints

Part of Epic: Student Experience & Gamification

---

#### 2.2 (#890) — Progress Tracking Engine

Progress tracking is the backbone of the student experience, providing real-time feedback on learning advancement. The engine tracks completion at three levels: lesson (binary complete/incomplete), module (percentage of completed lessons), and course (percentage of completed modules). Lesson completion is triggered explicitly when a student marks a lesson as done or implicitly when they pass an inline quiz.

The progress data model uses a `lesson_progress` table with `student_id`, `lesson_id`, `status` (not_started, in_progress, completed), `started_at`, `completed_at`, and `time_spent_seconds`. Module and course progress percentages are computed from lesson progress, cached in `module_progress` and `course_progress` tables, and refreshed on each lesson status change.

Time tracking uses heartbeat signals from the client: the lesson viewer sends a heartbeat every 30 seconds while the lesson is in the active browser tab, incrementing `time_spent_seconds`. This enables analytics on actual engagement time versus simple completion.

**Acceptance Criteria:**
- `POST /api/v1/academy/progress/lessons/{lessonId}/complete` marks lesson complete and cascades module/course percentage recalculation
- Module progress percentage computed as `(completed_lessons / total_lessons) * 100`, cached and updated on lesson change
- Course completion triggers when all modules reach 100%, updating enrollment status to `completed`
- Heartbeat endpoint `POST /api/v1/academy/progress/heartbeat` increments time tracking (idempotent within 30s window)
- `GET /api/v1/academy/progress/courses/{courseId}` returns full progress tree (course → modules → lessons) with percentages
- Resume position tracked: last accessed lesson ID stored for "Continue where you left off" functionality

**Tech Stack:** NextJS API routes, PostgreSQL with materialized progress cache, REST endpoints documented in OpenAPI 3.1

Part of Epic: Student Experience & Gamification

---

#### 2.3 (#891) — Student Dashboard

The student dashboard is the personalized home screen for learners, providing at-a-glance visibility into their learning journey. The dashboard displays three primary sections: "Continue Learning" (in-progress courses with progress bars and resume buttons), "Recommended For You" (courses based on completed courses and skill gaps), and "Recent Achievements" (recently earned badges and milestones).

The "Continue Learning" section shows course cards sorted by last accessed date, each displaying a progress bar, next lesson title, and estimated time to completion. A prominent "Resume" button deep-links directly to the last accessed lesson. The recommendations section uses a simple algorithm initially: courses tagged with the same categories as completed courses, excluding already-enrolled courses, sorted by popularity.

The dashboard also includes a learning streak indicator showing consecutive days of activity, a weekly goal tracker (configurable target: e.g., "Complete 3 lessons per week"), and a summary stats bar showing total courses completed, total time spent, and badges earned.

**Acceptance Criteria:**
- "Continue Learning" section shows up to 4 in-progress courses sorted by `last_accessed_at` with progress bars
- "Resume" button links to last accessed lesson within each course
- Recommendations section shows up to 6 courses using tag-based similarity, excluding enrolled courses
- Learning streak counter tracks consecutive calendar days with at least one lesson completion
- Weekly goal tracker shows progress toward configurable weekly lesson target (stored in user preferences)
- Stats bar displays: total courses completed, total hours spent learning, total badges earned

**Tech Stack:** NextJS page (`app/(platform)/academy/dashboard/page.tsx`), Radix UI Progress for progress bars, Radix UI Tooltip for streak info, server-side data aggregation queries

Part of Epic: Student Experience & Gamification

---

#### 2.4 (#892) — Badge & Achievement System

Badges provide gamified recognition for learning milestones, driving engagement through visible accomplishments. The system supports two badge categories: automatic (awarded by the system on milestone triggers) and manual (awarded by instructors or admins). Badge definitions are stored in a `badge_definition` table with fields for name, description, icon URL, category, and trigger criteria (JSON).

Automatic badge triggers include: completing a first course ("First Steps"), completing 5 courses ("Scholar"), maintaining a 7-day streak ("Dedicated Learner"), earning a certification ("Certified Pro"), and custom triggers defined per course by authors. The trigger evaluation engine runs asynchronously after each progress event, checking all applicable badge definitions against the student's cumulative stats.

Earned badges are displayed on the student's profile, the dashboard achievements section, and optionally on a public profile page. Students can share badges via generated Open Graph images suitable for LinkedIn and social media posting. Each badge award generates a notification and an optional email.

**Acceptance Criteria:**
- Badge definition CRUD API for admins with fields: name, description, icon_url, trigger_criteria (JSON), category (automatic/manual)
- Trigger evaluation engine processes progress events and awards matching badges asynchronously
- Built-in triggers: first_course_complete, courses_completed_count(n), streak_days(n), certification_earned
- `GET /api/v1/academy/users/{userId}/badges` returns earned badges with award dates
- Badge sharing generates OG image with badge icon, name, student name, and award date
- Duplicate award prevention: trigger engine is idempotent per (student_id, badge_definition_id)

**Tech Stack:** NextJS API routes, PostgreSQL for badge storage, background worker for trigger evaluation, Radix UI Dialog for badge detail modal, OG image generation via `@vercel/og` or similar

Part of Epic: Student Experience & Gamification

---

#### 2.5 (#893) — Leaderboards & Social Learning

Leaderboards introduce competitive motivation by ranking students within their tenant scope based on accumulated learning points. Points are earned through activities: completing a lesson (10 points), completing a module (50 points), completing a course (200 points), earning a badge (100 points), maintaining a daily streak (5 points per day). The point system is configurable per tenant.

The leaderboard UI displays three time windows: weekly, monthly, and all-time. Each shows the top 20 students with rank, avatar, display name, and point total. The current student's rank is always visible, even if they're outside the top 20, displayed in a pinned row. Leaderboards are tenant-scoped by default but can be further scoped to teams within enterprise tenants.

A "Learning Activity Feed" complements the leaderboard, showing a chronological stream of anonymized or opted-in learning events: "A colleague completed Advanced Schema Design," "3 people earned the API Expert badge this week." This fosters community without requiring direct social features.

**Acceptance Criteria:**
- Points awarded asynchronously on learning events with configurable point values per activity type
- `GET /api/v1/academy/leaderboard?window=weekly|monthly|alltime` returns top 20 with current user's rank
- Leaderboard scoped to tenant; enterprise tenants can further scope to teams via `teamId` query param
- Current user's rank always included in response even if outside top 20
- Radix UI Tabs for switching between weekly/monthly/all-time views
- Activity feed endpoint returns paginated stream of opt-in learning events within tenant

**Tech Stack:** NextJS page (`app/(platform)/academy/leaderboard/page.tsx`), Radix UI Tabs for time window, Radix UI Table for rankings, PostgreSQL materialized view refreshed on point changes

Part of Epic: Student Experience & Gamification

---

## Epic 3: Certification & Assessment Engine

### Summary Table

| #   | Title                              | Description                                                                    | Labels                                  | Parallel |
|-----|------------------------------------|--------------------------------------------------------------------------------|-----------------------------------------|----------|
| 3.1 (#895) | Assessment & Exam Data Model       | Schema for exams, questions, answer options, and grading rubrics               | `enhancement`, `academy`, `rest`        | Yes      |
| 3.2 (#896) | Exam Authoring Interface           | UI for creating timed exams with multiple question types and randomization     | `enhancement`, `academy`                | No       |
| 3.3 (#897) | Exam Taking Experience             | Proctored exam UI with timer, question navigation, and auto-submit            | `enhancement`, `academy`                | No       |
| 3.4 (#898) | Grading & Results Engine           | Automated grading, manual review queue, score calculation, and pass/fail       | `enhancement`, `academy`, `rest`        | No       |
| 3.5 (#899) | Certificate Generation & Verification | PDF certificate generation with unique verification codes and public verify page | `enhancement`, `academy`, `rest`      | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#895) — Assessment & Exam Data Model

The assessment engine requires a data model that supports multiple question types, timed exams, randomized question pools, and detailed grading rubrics. An `exam` record defines the exam metadata: title, description, associated course/certification, time limit in minutes, passing score percentage, max attempts, and whether questions are randomized.

Questions belong to a `question_pool` associated with an exam, enabling random selection of N questions from a larger pool for each attempt. Each `question` record has a type discriminator (multiple_choice, multi_select, true_false, short_answer, code_challenge), the question text (markdown), an optional explanation shown after grading, point value, and difficulty level. Answer options are stored in a `question_option` table for choice-based types, with `is_correct` flags.

An `exam_attempt` table captures each student's attempt: start time, end time, submitted answers (JSON), score, pass/fail status, and attempt number. The `exam_answer` table stores individual answers per question for detailed analytics and review.

**Acceptance Criteria:**
- Database migration creates exam, question_pool, question, question_option, exam_attempt, and exam_answer tables
- Question types supported: `multiple_choice`, `multi_select`, `true_false`, `short_answer`, `code_challenge`
- Exam configuration supports: time_limit_minutes, passing_score_percent, max_attempts, randomize_questions, pool_size
- Question pool supports drawing N random questions from M total (e.g., 30 random from 100)
- All tables tenant-scoped with proper foreign key relationships and indexes
- OpenAPI 3.1 component schemas defined for all exam-related entities

**Tech Stack:** PostgreSQL migrations, JSON Schema for answer validation, OpenAPI 3.1 component definitions

Part of Epic: Certification & Assessment Engine

---

#### 3.2 (#896) — Exam Authoring Interface

The exam authoring interface provides course authors and certification managers with a comprehensive tool for building assessments. The interface uses a two-panel layout: a left sidebar showing the question list with drag-and-drop reordering, and a main panel with the question editor. Authors switch between question types using a Radix UI Select dropdown, and the editor form adapts to show relevant fields for each type.

For multiple choice questions, authors enter the question text in a markdown editor, add answer options (minimum 2, maximum 8), mark one or more as correct, set a point value, and optionally add an explanation. For code challenge questions, authors provide a problem statement, starter code, test cases (input/expected output pairs), and a language selector. A preview mode renders the question exactly as students will see it.

Exam-level settings are configured in a settings panel: time limit, passing score, max attempts, question randomization toggle, and pool configuration (if randomization is on, how many questions to draw). A "Test Run" feature lets authors take their own exam in a sandboxed mode to verify the experience.

**Acceptance Criteria:**
- Question editor supports all 5 question types with type-specific form fields
- Drag-and-drop question reordering in the sidebar question list
- Markdown editor for question text with live preview
- Answer option management: add/remove options, mark correct, reorder for multiple choice types
- Exam settings panel with Radix UI form controls for time limit, passing score, max attempts, randomization
- "Test Run" mode creates a non-scored attempt for the author to preview the exam experience

**Tech Stack:** NextJS page (`app/(platform)/academy/exams/[examId]/edit/page.tsx`), Radix UI Select for question type, Radix UI Switch for randomization toggle, Radix UI Slider for passing score, CodeMirror for code challenge editor

Part of Epic: Certification & Assessment Engine

---

#### 3.3 (#897) — Exam Taking Experience

The exam taking experience is a focused, distraction-free interface designed for timed assessments. When a student starts an exam, the system creates an `exam_attempt` record with the start timestamp and calculates the end time based on the configured time limit. The UI enters a full-screen-like mode with the exam timer prominently displayed, a question navigator sidebar, and the active question in the main area.

Students navigate between questions using previous/next buttons or by clicking question numbers in the navigator. The navigator shows question status: unanswered (gray), answered (green), flagged for review (yellow). A "Flag for Review" toggle lets students mark questions they want to revisit. Answers are auto-saved to the server every 10 seconds and on each question navigation to prevent data loss.

When the timer reaches zero, the exam auto-submits with all current answers. Students can also manually submit early via a confirmation dialog. If the student loses connectivity, the client-side timer continues and queues answer saves for retry when connection resumes. A "time remaining" warning appears at 5 minutes and 1 minute.

**Acceptance Criteria:**
- Exam start creates attempt record and returns deadline timestamp; client renders countdown timer
- Question navigator sidebar shows all questions with status indicators (unanswered/answered/flagged)
- Auto-save answers every 10 seconds and on question navigation via `PATCH /api/v1/academy/attempts/{id}/answers`
- Auto-submit triggers when timer reaches zero, submitting all saved answers
- Manual submit requires Radix UI AlertDialog confirmation ("Are you sure? You have X unanswered questions")
- Time warnings displayed as toast notifications at 5-minute and 1-minute marks

**Tech Stack:** NextJS page (`app/(platform)/academy/exams/[examId]/take/page.tsx`), Radix UI AlertDialog for submit confirmation, Radix UI Toast for time warnings, client-side timer with server-side deadline validation

Part of Epic: Certification & Assessment Engine

---

#### 3.4 (#898) — Grading & Results Engine

The grading engine processes submitted exam attempts to calculate scores and determine pass/fail outcomes. Auto-grading handles objective question types immediately: multiple choice, multi-select, and true/false are scored by comparing student answers against correct answer flags. Short answer questions use exact match or regex patterns defined by the author. Code challenges are evaluated by running student code against test cases in a sandboxed execution environment.

For questions requiring manual review (complex short answers, subjective code quality assessment), the system queues the attempt in a review workflow. Reviewers see the student's answers alongside the rubric and can assign partial credit. The attempt remains in "pending_review" status until all manually graded questions are scored.

The results page shows the student their score breakdown: overall percentage, points earned per question, correct/incorrect indicators, and the author's explanations for each question. If the student failed, they see the number of remaining attempts (if any) and a "Retake" button. Score data feeds into the progress tracking engine, and passing an exam associated with a certification triggers the certificate generation pipeline.

**Acceptance Criteria:**
- Auto-grading completes within 5 seconds for objective question types (multiple choice, multi-select, true/false)
- Short answer grading supports exact match and regex pattern matching defined in question configuration
- Manual review queue accessible at `/academy/exams/reviews` with filters for exam, status, and date range
- Results page shows per-question breakdown with score, correct answer, and explanation
- Pass/fail determination based on configurable passing_score_percent with result stored on attempt
- Passing a certification exam triggers async event for certificate generation (consumed by issue 3.5)

**Tech Stack:** NextJS API routes for grading, background worker for code challenge evaluation, Radix UI Table for review queue, REST endpoints for results retrieval

Part of Epic: Certification & Assessment Engine

---

#### 3.5 (#899) — Certificate Generation & Verification

Certificates are PDF documents generated when a student passes a certification exam, providing verifiable proof of competency. Each certificate contains: the student's name, certification title, date of achievement, a unique verification code (UUID-based), the issuing organization (tenant name), and a QR code linking to the public verification page.

The generation pipeline is triggered asynchronously by the grading engine's pass event. A background worker renders the certificate using a configurable template (HTML/CSS rendered to PDF), stores it in S3, and creates a `certificate` record with the verification code, student ID, certification ID, issue date, and expiry date (if applicable). Students receive a notification with a download link.

The public verification page (`/verify/{code}`) requires no authentication and displays the certificate details: holder name, certification name, issue date, and validity status. This enables employers and third parties to verify certificate authenticity. An API endpoint `GET /api/v1/academy/certificates/verify/{code}` returns the same data as JSON for programmatic verification.

**Acceptance Criteria:**
- Certificate PDF generated from HTML template with student name, certification title, date, verification code, and QR code
- PDF stored in S3 with download URL accessible to the certificate holder
- Unique verification code (UUID v4) generated per certificate and stored in database
- Public verification page at `/verify/{code}` displays certificate details without requiring authentication
- JSON verification endpoint `GET /api/v1/academy/certificates/verify/{code}` returns structured certificate data
- Certificates support optional expiry dates; verification page shows "Expired" status for expired certificates

**Tech Stack:** NextJS page (`app/verify/[code]/page.tsx` — public route), background worker for PDF generation (Puppeteer or similar), S3 storage for PDF files, QR code generation library

Part of Epic: Certification & Assessment Engine

---

## Epic 4: Enterprise Training & Integration

### Summary Table

| #   | Title                              | Description                                                                     | Labels                                   | Parallel |
|-----|------------------------------------|---------------------------------------------------------------------------------|------------------------------------------|----------|
| 4.1 (#901) | Custom Curricula Builder           | Enterprise admins create custom training paths from available courses            | `enhancement`, `academy`, `rest`         | Yes      |
| 4.2 (#902) | Team Assignment & Tracking         | Assign curricula to teams/individuals with deadline management and reminders     | `enhancement`, `academy`, `rest`         | No       |
| 4.3 (#903) | HR System Integration Connectors   | Integrate with Workday, BambooHR, and generic SCIM for employee sync            | `enhancement`, `academy`, `rest`         | Yes      |
| 4.4 (#904) | Compliance Tracking & Reporting    | Track mandatory training completion, generate compliance reports, alert on gaps  | `enhancement`, `academy`, `rest`         | No       |
| 4.5 (#905) | Enterprise Analytics Dashboard     | Training ROI, team progress, skill gap analysis, and exportable reports          | `enhancement`, `academy`                 | Yes      |

### Detailed Issue Descriptions

#### 4.1 (#901) — Custom Curricula Builder

Enterprise training managers need the ability to assemble custom training paths (curricula) from the available course catalog, tailoring the learning experience to their organization's specific needs. A curriculum is an ordered collection of courses with optional deadlines per course, prerequisites overrides, and custom descriptions explaining why each course is relevant to the organization.

The curricula builder UI provides a drag-and-drop interface where training managers search the course catalog, add courses to the curriculum, and arrange them in the desired sequence. Each course in the curriculum can be marked as required or optional, assigned an estimated completion deadline (relative to enrollment: e.g., "complete within 2 weeks"), and annotated with organizational context.

Curricula support versioning: when a training manager updates a curriculum (adds/removes/reorders courses), a new version is created. Students enrolled in the previous version continue with their version unless explicitly migrated. The API supports CRUD operations on curricula with tenant-scoped access control.

```
┌─────────────────────────────────────────────────┐
│              Curriculum Builder                  │
├───────────────────────┬─────────────────────────┤
│   Course Catalog      │   Curriculum Canvas     │
│                       │                         │
│  [Search courses...]  │  1. ▣ Schema Basics     │
│                       │     Required · 1 week   │
│  ┌─────────────────┐  │  2. ▣ API Design 101    │
│  │ Schema Basics   │──┼──▶  Required · 2 weeks  │
│  │ ★★★★☆  2h      │  │  3. ☐ Advanced Patterns │
│  └─────────────────┘  │     Optional · 3 weeks  │
│  ┌─────────────────┐  │  4. ▣ Certification     │
│  │ API Design 101  │  │     Required · 4 weeks  │
│  │ ★★★★★  4h      │  │                         │
│  └─────────────────┘  │  [+ Add Course]         │
│  ┌─────────────────┐  │                         │
│  │ Adv. Patterns   │  ├─────────────────────────┤
│  │ ★★★☆☆  6h      │  │ Settings  │  Preview    │
│  └─────────────────┘  │ Version: 2.0            │
│  ...                  │ Total est: 15 hours     │
└───────────────────────┴─────────────────────────┘
```

**Acceptance Criteria:**
- CRUD API for curricula at `/api/v1/academy/curricula` with tenant-scoped access
- Drag-and-drop course ordering within curriculum with required/optional flag per course
- Per-course relative deadline support (e.g., "complete within N days of enrollment")
- Curriculum versioning: updates create new versions; enrolled students stay on their version
- Curriculum detail page shows completion statistics across all enrolled students
- Maximum 50 courses per curriculum enforced at API level

**Tech Stack:** NextJS page (`app/(platform)/academy/curricula/[curriculumId]/edit/page.tsx`), Radix UI Dialog for course addition, drag-and-drop library, REST API with OpenAPI 3.1

Part of Epic: Enterprise Training & Integration

---

#### 4.2 (#902) — Team Assignment & Tracking

Enterprise training managers assign curricula to teams or individual employees with configurable deadlines and automated reminders. An assignment record links a curriculum version to either a team (all current members) or specific user IDs, with a start date and absolute deadline. When a team assignment is created, the system enrolls all current team members and watches for new team members to auto-enroll.

The assignment tracking dashboard shows training managers a matrix view: rows are assigned employees, columns are courses in the curriculum, and cells show completion status (not started, in progress, completed, overdue). Color coding highlights overdue items in red. Managers can filter by team, status, and deadline range, and drill down into individual progress.

Automated reminders are sent via email and in-app notification at configurable intervals: when an assignment is created, at 50% of the deadline elapsed, at 75%, and when overdue. Managers can also send manual nudge notifications to specific individuals. Escalation rules allow configuring automatic manager notification when an employee is overdue by N days.

**Acceptance Criteria:**
- Assignment API: `POST /api/v1/academy/assignments` accepts curriculum_id, target (team_id or user_ids array), start_date, deadline
- Team assignments auto-enroll current members and watch for new members (via team membership webhook or polling)
- Tracking dashboard matrix view with rows=employees, columns=courses, cells=status with color coding
- Automated reminder notifications at configurable intervals (assignment creation, 50%, 75%, overdue)
- Manual nudge endpoint: `POST /api/v1/academy/assignments/{id}/nudge` sends notification to specified users
- Overdue escalation: configurable N-day overdue threshold triggers manager notification

**Tech Stack:** NextJS page (`app/(platform)/academy/assignments/page.tsx`), Radix UI Table for matrix view, background job scheduler for reminders, notification service integration

Part of Epic: Enterprise Training & Integration

---

#### 4.3 (#903) — HR System Integration Connectors

Enterprise customers need Academy to integrate with their HR systems for employee data synchronization, ensuring training records stay current as employees join, leave, or change roles. The integration layer supports three connector types: Workday (REST API), BambooHR (REST API), and generic SCIM 2.0 for any SCIM-compliant HR system.

Each connector syncs employee profiles (name, email, department, role, manager), team/department structures, and employment status (active, terminated, on leave). Inbound sync ensures new employees are automatically assigned mandatory training curricula based on their department/role mapping rules. Outbound sync pushes training completion records back to the HR system for compliance tracking.

The connector configuration UI allows enterprise admins to set up credentials (stored encrypted), map HR system fields to Academy user attributes, configure sync frequency (hourly, daily, or webhook-triggered), and test the connection. A sync log shows the history of sync operations with success/failure counts and error details.

**Acceptance Criteria:**
- Connector configuration API: `POST /api/v1/academy/integrations/hr` with provider type, credentials (encrypted), and field mapping
- Workday connector: sync employees, departments, and employment status via Workday REST API
- BambooHR connector: sync employees and departments via BambooHR API
- Generic SCIM 2.0 connector: inbound user provisioning and deprovisioning via SCIM endpoints
- Auto-assignment rules: configure department/role → curriculum mappings for automatic enrollment on sync
- Sync log with history, success/failure counts, and per-record error details at `/api/v1/academy/integrations/hr/{id}/logs`

**Tech Stack:** NextJS API routes for connector management, encrypted credential storage, background sync workers, SCIM 2.0 server endpoints, Radix UI Dialog for connector setup wizard

Part of Epic: Enterprise Training & Integration

---

#### 4.4 (#904) — Compliance Tracking & Reporting

Regulated industries require proof that employees have completed mandatory training within specified timeframes. The compliance tracking module enables training managers to mark curricula as compliance-required, associate them with regulatory frameworks (e.g., SOC 2, HIPAA, GDPR), and set recurring completion requirements (annual recertification).

The compliance dashboard shows an organization-wide view of compliance status: percentage of employees compliant per requirement, employees approaching deadline, and employees overdue. Drill-down views show per-department and per-individual compliance status. Critical alerts fire when compliance percentage drops below configurable thresholds (e.g., below 90%).

Compliance reports are generated on demand or on a schedule, exportable as PDF and Excel. Reports include: employee name, required training, completion date, expiry date, current status, and manager name. An audit trail logs all compliance status changes for regulatory evidence. The system supports "compliance holds" that prevent removing completed training records during audit periods.

**Acceptance Criteria:**
- Curricula can be flagged as compliance-required with associated regulatory framework tags
- Recurring requirements support: annual, semi-annual, quarterly recertification with auto-assignment on expiry
- Compliance dashboard shows org-wide compliance percentage with department drill-down
- Alert system fires when compliance percentage drops below configurable threshold per requirement
- Report generation endpoint: `POST /api/v1/academy/compliance/reports` produces PDF/Excel with employee compliance data
- Audit trail for all compliance status changes (completion, expiry, exemption) with actor and timestamp

**Tech Stack:** NextJS page (`app/(platform)/academy/compliance/page.tsx`), Radix UI Table for compliance matrix, PDF generation library, Excel export via `xlsx` library, background job for recurring requirement evaluation

Part of Epic: Enterprise Training & Integration

---

#### 4.5 (#905) — Enterprise Analytics Dashboard

The enterprise analytics dashboard provides training managers and executives with data-driven insights into training program effectiveness, team skill development, and ROI. The dashboard surfaces four key metric categories: engagement (active learners, time spent, course starts vs completions), effectiveness (assessment scores, certification pass rates, skill improvements), efficiency (time-to-completion, cost-per-trained-employee), and coverage (percentage of workforce trained, skill gap analysis).

Visualizations include time-series charts for engagement trends, bar charts for department comparisons, funnel charts for course completion rates, and heatmaps for skill coverage across teams. All charts support date range filtering and department/team scoping. A "Skill Gap Analysis" view compares required skills (from job role definitions) against earned certifications and completed courses to identify training priorities.

Export capabilities allow managers to download dashboard data as CSV for further analysis, generate scheduled PDF reports for executive distribution, and embed dashboard widgets in external portals via iframe with authentication tokens. A custom report builder enables creating saved report configurations with selected metrics, filters, and groupings.

**Acceptance Criteria:**
- Dashboard page with engagement, effectiveness, efficiency, and coverage metric cards
- Time-series charts for learner engagement trends with configurable date range (7d, 30d, 90d, custom)
- Department comparison bar charts with drill-down to team and individual level
- Skill gap analysis view comparing role requirements against training completions
- Export to CSV/PDF with scheduled report delivery via email (daily, weekly, monthly)
- Dashboard data API: `GET /api/v1/academy/analytics/dashboard` with query params for date range, department, team

**Tech Stack:** NextJS page (`app/(platform)/academy/analytics/page.tsx`), charting library (Recharts or similar), Radix UI Select for date range, PDF report generation, CSV export endpoint

Part of Epic: Enterprise Training & Integration

---

## Parallel Work Guide

The following issues can be worked on simultaneously within and across epics:

**Epic 1 — Course Management Platform:**
- Issues 1.1, 1.3, and 1.4 can all be developed in parallel (data model, editor UI, and media pipeline are independent)
- Issue 1.2 depends on 1.1 (API needs the data model)
- Issue 1.5 depends on 1.2 (catalog UI needs the API)
- Issue 1.6 depends on 1.2 (publishing workflow needs the course API)

**Epic 2 — Student Experience & Gamification:**
- Issues 2.1, 2.4, and 2.5 can be developed in parallel (enrollment, badges, and leaderboards are independent)
- Issue 2.2 depends on 2.1 (progress tracking needs enrollment records)
- Issue 2.3 depends on 2.2 (dashboard needs progress data)

**Epic 3 — Certification & Assessment:**
- Issues 3.1 and 3.5 can start in parallel (data model and certificate template/generation are independent)
- Issue 3.2 depends on 3.1 (exam editor needs the data model)
- Issue 3.3 depends on 3.2 (exam taking needs authored exams)
- Issue 3.4 depends on 3.3 (grading needs submitted attempts)
- Issue 3.5 certificate triggering depends on 3.4 (generation triggered by grading)

**Epic 4 — Enterprise Training & Integration:**
- Issues 4.1, 4.3, and 4.5 can be developed in parallel (curricula builder, HR connectors, and analytics are independent)
- Issue 4.2 depends on 4.1 (assignments need curricula)
- Issue 4.4 depends on 4.2 (compliance tracking needs assignment data)

**Cross-Epic Parallelism:**
- Epic 1 and Epic 2 (issues 2.1, 2.4, 2.5) can begin simultaneously
- Epic 3 (issue 3.1) can start once Epic 1 course structure is defined
- Epic 4 can start in parallel with Epics 2 and 3 (curricula are built on top of courses from Epic 1)

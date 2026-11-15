-- Suggested changes on a review — COL-4.2 (#4526).
--
-- "Request changes" with a prose note forces the author to re-type the reviewer's intent. A
-- suggestion is that intent made concrete: an RFC 6902 JSON patch over one model element of the
-- version under review, which the author applies or rejects in one click.
--
--   review_suggestions — one proposed edit to one class or property, attached to a review.
--
-- Rules:
--
--   1. **The element, not the document.** A suggestion targets one element by id (``class`` →
--      ``apiome.classes``, ``property`` → ``apiome.class_properties``) and patches its canonical
--      JSON: ``{"description", "schema"}`` for a class, ``{"description", "data"}`` for a property.
--   2. **Base, patch, and proposed are all kept.** ``base`` is the element when the suggestion was
--      made and ``proposed`` the patch applied to it. Applying merges ``base`` / current /
--      ``proposed`` three ways with the merge-session engine, so an edit made since is either merged
--      around or reported as a conflict (``stale``) — never silently overwritten.
--   3. **A decision is final.** ``applied``, ``rejected``, and ``stale`` are recorded with who and
--      when; only an ``open`` suggestion can be decided.
--
-- Rollback notes:
--   DROP TABLE IF EXISTS apiome.review_suggestions;

SET search_path TO apiome, public;

CREATE TABLE IF NOT EXISTS review_suggestions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
    author_id UUID REFERENCES users(id) ON DELETE SET NULL,
    target_type VARCHAR(16) NOT NULL
        CONSTRAINT review_suggestions_target_type_check CHECK (target_type IN ('class', 'property')),
    target_id UUID NOT NULL,
    target_label VARCHAR(512) NOT NULL,
    note TEXT
        CONSTRAINT review_suggestions_note_check CHECK (note IS NULL OR length(note) <= 5000),
    base JSONB NOT NULL,
    patch JSONB NOT NULL
        CONSTRAINT review_suggestions_patch_check CHECK (
            jsonb_typeof(patch) = 'array' AND jsonb_array_length(patch) BETWEEN 1 AND 50
        ),
    proposed JSONB NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open'
        CONSTRAINT review_suggestions_status_check CHECK (status IN ('open', 'applied', 'rejected', 'stale')),
    conflict_paths TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    decided_by UUID REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMP WITH TIME ZONE,
    reason TEXT
        CONSTRAINT review_suggestions_reason_check CHECK (reason IS NULL OR length(reason) <= 5000),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT review_suggestions_decided_check CHECK ((status = 'open') = (decided_at IS NULL)),
    CONSTRAINT review_suggestions_size_check CHECK (
        octet_length(base::text) <= 262144 AND octet_length(proposed::text) <= 262144
    )
);

CREATE INDEX IF NOT EXISTS idx_review_suggestions_review ON review_suggestions (review_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_review_suggestions_target ON review_suggestions (target_type, target_id);

COMMENT ON TABLE review_suggestions IS
    'A reviewer''s concrete edit to one class or property of a version under review, applied or rejected by its author (COL-4.2, #4526)';

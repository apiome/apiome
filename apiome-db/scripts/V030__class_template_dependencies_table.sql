-- Class Template Dependencies Table
-- Stores dependencies between class templates for $ref support

SET search_path TO apiome, public;

-- Drop existing table if exists
DROP TABLE IF EXISTS class_template_dependencies CASCADE;

CREATE TABLE class_template_dependencies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- The template that has the dependency
    template_id UUID NOT NULL REFERENCES class_templates(id) ON DELETE CASCADE,

    -- The template that is required/depended upon
    depends_on_template_id UUID NOT NULL REFERENCES class_templates(id) ON DELETE CASCADE,

    -- Reference path used in the schema (e.g., "#/components/schemas/Address")
    ref_path VARCHAR(500),

    -- Property name where this dependency is used
    property_name VARCHAR(255),

    -- Whether this dependency is required (not optional)
    is_required BOOLEAN NOT NULL DEFAULT true,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Prevent duplicate dependencies
    CONSTRAINT class_template_deps_unique UNIQUE (template_id, depends_on_template_id, property_name),

    -- Prevent self-referencing
    CONSTRAINT class_template_deps_no_self_ref CHECK (template_id != depends_on_template_id)
);

-- Table comment
COMMENT ON TABLE class_template_dependencies IS 'Stores dependencies between class templates, enabling $ref support when creating classes from templates. Dependencies are identified by template ID to handle multiple templates with the same name.';

-- Column comments
COMMENT ON COLUMN class_template_dependencies.id IS 'Unique identifier for the dependency record';
COMMENT ON COLUMN class_template_dependencies.template_id IS 'The template that has the dependency';
COMMENT ON COLUMN class_template_dependencies.depends_on_template_id IS 'The template that is required/depended upon';
COMMENT ON COLUMN class_template_dependencies.ref_path IS 'Reference path used in the schema (e.g., "#/components/schemas/Address")';
COMMENT ON COLUMN class_template_dependencies.property_name IS 'Property name where this dependency is used';
COMMENT ON COLUMN class_template_dependencies.is_required IS 'Whether this dependency is required';
COMMENT ON COLUMN class_template_dependencies.created_at IS 'Timestamp when the dependency was created';

-- Indices for performance
CREATE INDEX idx_class_template_deps_template_id ON class_template_dependencies(template_id);
CREATE INDEX idx_class_template_deps_depends_on ON class_template_dependencies(depends_on_template_id);

-- Add some example dependencies to existing templates
-- Order depends on Address (for shipping/billing addresses)
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    o.id as template_id,
    a.id as depends_on_template_id,
    '#/components/schemas/Address' as ref_path,
    'shippingAddress' as property_name,
    false as is_required
FROM class_templates o, class_templates a
WHERE o.name = 'Order' AND o.is_system = true
  AND a.name = 'Address' AND a.is_system = true
ON CONFLICT DO NOTHING;

INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    o.id as template_id,
    a.id as depends_on_template_id,
    '#/components/schemas/Address' as ref_path,
    'billingAddress' as property_name,
    false as is_required
FROM class_templates o, class_templates a
WHERE o.name = 'Order' AND o.is_system = true
  AND a.name = 'Address' AND a.is_system = true
ON CONFLICT DO NOTHING;

-- Order depends on OrderItem (for line items)
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    o.id as template_id,
    oi.id as depends_on_template_id,
    '#/components/schemas/OrderItem' as ref_path,
    'items' as property_name,
    true as is_required
FROM class_templates o, class_templates oi
WHERE o.name = 'Order' AND o.is_system = true
  AND oi.name = 'OrderItem' AND oi.is_system = true
ON CONFLICT DO NOTHING;

-- User depends on UserProfile
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    u.id as template_id,
    up.id as depends_on_template_id,
    '#/components/schemas/UserProfile' as ref_path,
    'profile' as property_name,
    false as is_required
FROM class_templates u, class_templates up
WHERE u.name = 'User' AND u.is_system = true
  AND up.name = 'UserProfile' AND up.is_system = true
ON CONFLICT DO NOTHING;

-- User depends on Address
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    u.id as template_id,
    a.id as depends_on_template_id,
    '#/components/schemas/Address' as ref_path,
    'address' as property_name,
    false as is_required
FROM class_templates u, class_templates a
WHERE u.name = 'User' AND u.is_system = true
  AND a.name = 'Address' AND a.is_system = true
ON CONFLICT DO NOTHING;

-- BlogPost depends on Comment
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    bp.id as template_id,
    c.id as depends_on_template_id,
    '#/components/schemas/Comment' as ref_path,
    'comments' as property_name,
    false as is_required
FROM class_templates bp, class_templates c
WHERE bp.name = 'BlogPost' AND bp.is_system = true
  AND c.name = 'Comment' AND c.is_system = true
ON CONFLICT DO NOTHING;

-- BlogPost depends on Tag
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    bp.id as template_id,
    t.id as depends_on_template_id,
    '#/components/schemas/Tag' as ref_path,
    'tags' as property_name,
    false as is_required
FROM class_templates bp, class_templates t
WHERE bp.name = 'BlogPost' AND bp.is_system = true
  AND t.name = 'Tag' AND t.is_system = true
ON CONFLICT DO NOTHING;

-- Product depends on File (for images)
INSERT INTO class_template_dependencies (template_id, depends_on_template_id, ref_path, property_name, is_required)
SELECT
    p.id as template_id,
    f.id as depends_on_template_id,
    '#/components/schemas/File' as ref_path,
    'images' as property_name,
    false as is_required
FROM class_templates p, class_templates f
WHERE p.name = 'Product' AND p.is_system = true
  AND f.name = 'File' AND f.is_system = true
ON CONFLICT DO NOTHING;


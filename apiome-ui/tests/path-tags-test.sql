-- Path Tags Functionality Test
-- This script tests the path_tags table and related functionality
-- Run this after applying the 20260101-120000.sql migration

SET search_path TO apiome, public;

-- ============================================================================
-- TEST SETUP
-- Create test data for paths and tags
-- ============================================================================

DO $$
DECLARE
    test_tenant_id UUID;
    test_user_id UUID;
    test_project_id UUID;
    test_version_id UUID;
    test_path_id UUID;
    test_tag1_id UUID;
    test_tag2_id UUID;
    test_tag3_id UUID;
BEGIN
    -- Find or create test tenant
    SELECT id INTO test_tenant_id FROM tenants WHERE name = 'Test Tenant' LIMIT 1;
    IF test_tenant_id IS NULL THEN
        INSERT INTO tenants (name, slug)
        VALUES ('Test Tenant', 'test-tenant')
        RETURNING id INTO test_tenant_id;
    END IF;

    -- Find or create test user
    SELECT id INTO test_user_id FROM users WHERE email = 'test@example.com' LIMIT 1;
    IF test_user_id IS NULL THEN
        INSERT INTO users (email, name, tenant_id)
        VALUES ('test@example.com', 'Test User', test_tenant_id)
        RETURNING id INTO test_user_id;
    END IF;

    -- Find or create test project
    SELECT id INTO test_project_id FROM projects WHERE name = 'Test Project' AND tenant_id = test_tenant_id LIMIT 1;
    IF test_project_id IS NULL THEN
        INSERT INTO projects (tenant_id, name, description, created_by)
        VALUES (test_tenant_id, 'Test Project', 'Project for testing path tags', test_user_id)
        RETURNING id INTO test_project_id;
    END IF;

    -- Find or create test version
    SELECT id INTO test_version_id FROM versions WHERE project_id = test_project_id AND name = 'v1.0.0' LIMIT 1;
    IF test_version_id IS NULL THEN
        INSERT INTO versions (project_id, name, description)
        VALUES (test_project_id, 'v1.0.0', 'Test version')
        RETURNING id INTO test_version_id;
    END IF;

    -- Create test path
    INSERT INTO api_paths (version_id, path, summary, description)
    VALUES (test_version_id, '/api/users/{userId}', 'User operations', 'Operations for managing users')
    ON CONFLICT (version_id, path) DO NOTHING
    RETURNING id INTO test_path_id;

    IF test_path_id IS NULL THEN
        SELECT id INTO test_path_id FROM api_paths WHERE version_id = test_version_id AND path = '/api/users/{userId}';
    END IF;

    -- Create test tags
    INSERT INTO tags (project_id, name, color, description)
    VALUES
        (test_project_id, 'User Management', '#3B82F6', 'User domain operations'),
        (test_project_id, 'Public API', '#10B981', 'Publicly accessible endpoints'),
        (test_project_id, 'Beta', '#F59E0B', 'Beta features')
    ON CONFLICT (project_id, name) DO NOTHING;

    SELECT id INTO test_tag1_id FROM tags WHERE project_id = test_project_id AND name = 'User Management';
    SELECT id INTO test_tag2_id FROM tags WHERE project_id = test_project_id AND name = 'Public API';
    SELECT id INTO test_tag3_id FROM tags WHERE project_id = test_project_id AND name = 'Beta';

    -- ============================================================================
    -- TEST 1: Assign tags to path
    -- ============================================================================
    RAISE NOTICE 'TEST 1: Assigning tags to path...';

    INSERT INTO path_tags (path_id, tag_id)
    VALUES
        (test_path_id, test_tag1_id),
        (test_path_id, test_tag2_id)
    ON CONFLICT (path_id, tag_id) DO NOTHING;

    RAISE NOTICE '  ✓ Tags assigned successfully';

    -- ============================================================================
    -- TEST 2: Query tags for a path
    -- ============================================================================
    RAISE NOTICE 'TEST 2: Querying tags for path...';

    PERFORM pt.id
    FROM path_tags pt
    JOIN tags t ON pt.tag_id = t.id
    WHERE pt.path_id = test_path_id;

    IF FOUND THEN
        RAISE NOTICE '  ✓ Tags query successful';
    ELSE
        RAISE NOTICE '  ✗ No tags found for path';
    END IF;

    -- ============================================================================
    -- TEST 3: Verify unique constraint
    -- ============================================================================
    RAISE NOTICE 'TEST 3: Testing unique constraint...';

    BEGIN
        INSERT INTO path_tags (path_id, tag_id)
        VALUES (test_path_id, test_tag1_id);
        RAISE NOTICE '  ✗ Unique constraint failed - duplicate was allowed!';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE '  ✓ Unique constraint working - duplicate prevented';
    END;

    -- ============================================================================
    -- TEST 4: Replace all tags (transaction test)
    -- ============================================================================
    RAISE NOTICE 'TEST 4: Testing tag replacement (transaction)...';

    -- Delete all existing tags
    DELETE FROM path_tags WHERE path_id = test_path_id;

    -- Insert new set of tags
    INSERT INTO path_tags (path_id, tag_id)
    VALUES
        (test_path_id, test_tag2_id),
        (test_path_id, test_tag3_id);

    -- Verify count
    IF (SELECT COUNT(*) FROM path_tags WHERE path_id = test_path_id) = 2 THEN
        RAISE NOTICE '  ✓ Tag replacement successful';
    ELSE
        RAISE NOTICE '  ✗ Tag replacement failed';
    END IF;

    -- ============================================================================
    -- TEST 5: Remove a single tag
    -- ============================================================================
    RAISE NOTICE 'TEST 5: Removing a single tag...';

    DELETE FROM path_tags WHERE path_id = test_path_id AND tag_id = test_tag3_id;

    IF (SELECT COUNT(*) FROM path_tags WHERE path_id = test_path_id) = 1 THEN
        RAISE NOTICE '  ✓ Tag removal successful';
    ELSE
        RAISE NOTICE '  ✗ Tag removal failed';
    END IF;

    -- ============================================================================
    -- TEST 6: Cascade delete test
    -- ============================================================================
    RAISE NOTICE 'TEST 6: Testing cascade delete...';

    -- Create a temporary path to test deletion
    INSERT INTO api_paths (version_id, path, summary)
    VALUES (test_version_id, '/api/test/delete', 'Test path for deletion')
    RETURNING id INTO test_path_id;

    -- Assign a tag to it
    INSERT INTO path_tags (path_id, tag_id)
    VALUES (test_path_id, test_tag1_id);

    -- Delete the path
    DELETE FROM api_paths WHERE id = test_path_id;

    -- Check if the path_tag was also deleted
    IF NOT EXISTS (SELECT 1 FROM path_tags WHERE path_id = test_path_id) THEN
        RAISE NOTICE '  ✓ Cascade delete working correctly';
    ELSE
        RAISE NOTICE '  ✗ Cascade delete failed';
    END IF;

    -- ============================================================================
    -- TEST SUMMARY
    -- ============================================================================
    RAISE NOTICE '';
    RAISE NOTICE '============================================';
    RAISE NOTICE 'PATH TAGS FUNCTIONALITY TEST COMPLETED';
    RAISE NOTICE '============================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Review the output above for any failures (✗)';
    RAISE NOTICE 'All tests should show success (✓)';
    RAISE NOTICE '';

END $$;

-- ============================================================================
-- DISPLAY CURRENT STATE
-- ============================================================================
SELECT
    ap.path,
    STRING_AGG(t.name, ', ' ORDER BY t.name) as tags,
    COUNT(pt.id) as tag_count
FROM api_paths ap
LEFT JOIN path_tags pt ON ap.id = pt.path_id
LEFT JOIN tags t ON pt.tag_id = t.id
WHERE ap.deleted_at IS NULL
GROUP BY ap.id, ap.path
ORDER BY ap.path
LIMIT 10;


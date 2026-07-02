# Test Plan: Class Rename with $ref Updates

## Test Setup

### Initial State:
```
Version: "1.0.0"

Classes:
1. User
   - id: string
   - name: string
   - email: string

2. Team
   - id: string
   - name: string
   - owner: $ref(User)           ← Direct reference
   - members: array[$ref(User)]   ← Array reference

3. Project  
   - id: string
   - title: string
   - lead: $ref(User)             ← Direct reference
   - contributors: array[$ref(User)] ← Array reference
```

### Expected $ref Paths Before Rename:
```json
// Team.owner
{
  "$ref": "#/components/schemas/User"
}

// Team.members
{
  "type": "array",
  "items": {
    "$ref": "#/components/schemas/User"
  }
}

// Project.lead
{
  "$ref": "#/components/schemas/User"
}

// Project.contributors
{
  "type": "array",
  "items": {
    "$ref": "#/components/schemas/User"
  }
}
```

## Test Case 1: Simple Rename

### Action:
```javascript
await updateClass(
  userClassId,
  "Person",  // New name
  "A person in the system",
  userSchema
);
```

### Expected Results:
✅ Class renamed: `User` → `Person`

✅ Team.owner updated:
```json
{
  "$ref": "#/components/schemas/Person"
}
```

✅ Team.members updated:
```json
{
  "type": "array",
  "items": {
    "$ref": "#/components/schemas/Person"
  }
}
```

✅ Project.lead updated:
```json
{
  "$ref": "#/components/schemas/Person"
}
```

✅ Project.contributors updated:
```json
{
  "type": "array",
  "items": {
    "$ref": "#/components/schemas/Person"
  }
}
```

### Verification Queries:
```sql
-- Check class was renamed
SELECT name FROM apiome.classes WHERE id = '{userClassId}';
-- Expected: "Person"

-- Check Team.owner reference
SELECT data->'$ref' FROM apiome.class_properties 
WHERE class_id = '{teamClassId}' AND name = 'owner';
-- Expected: "#/components/schemas/Person"

-- Check Team.members reference
SELECT data->'items'->'$ref' FROM apiome.class_properties 
WHERE class_id = '{teamClassId}' AND name = 'members';
-- Expected: "#/components/schemas/Person"

-- Check Project.lead reference
SELECT data->'$ref' FROM apiome.class_properties 
WHERE class_id = '{projectClassId}' AND name = 'lead';
-- Expected: "#/components/schemas/Person"

-- Check Project.contributors reference
SELECT data->'items'->'$ref' FROM apiome.class_properties 
WHERE class_id = '{projectClassId}' AND name = 'contributors';
-- Expected: "#/components/schemas/Person"
```

## Test Case 2: No Name Change

### Action:
```javascript
await updateClass(
  userClassId,
  "User",  // Same name
  "Updated description",
  userSchema
);
```

### Expected Results:
✅ Class description updated
✅ Class name unchanged
✅ No property updates executed (optimization)
✅ All references remain as `#/components/schemas/User`

## Test Case 3: Class With No References

### Setup:
```
Class: Settings (standalone, no other classes reference it)
```

### Action:
```javascript
await updateClass(
  settingsClassId,
  "Configuration",
  "System configuration",
  settingsSchema
);
```

### Expected Results:
✅ Class renamed: `Settings` → `Configuration`
✅ No property updates needed
✅ No errors thrown

## Test Case 4: Self-Reference

### Setup:
```
Class: TreeNode
  - id: string
  - value: string
  - parent: $ref(TreeNode)     ← Self-reference
  - children: array[$ref(TreeNode)]  ← Self-reference
```

### Action:
```javascript
await updateClass(
  treeNodeClassId,
  "Node",
  "A tree node",
  treeNodeSchema
);
```

### Expected Results:
✅ Class renamed: `TreeNode` → `Node`
✅ TreeNode.parent updated to `$ref: #/components/schemas/Node`
✅ TreeNode.children.items updated to `$ref: #/components/schemas/Node`

## Test Case 5: Circular References

### Setup:
```
Class: Author
  - id: string
  - name: string
  - books: array[$ref(Book)]

Class: Book
  - id: string
  - title: string
  - author: $ref(Author)
```

### Action:
```javascript
await updateClass(
  authorClassId,
  "Writer",
  "A book writer",
  authorSchema
);
```

### Expected Results:
✅ Author renamed to "Writer"
✅ Book.author updated to `$ref: #/components/schemas/Writer`
✅ Writer.books still references `$ref: #/components/schemas/Book`

## Test Case 6: Duplicate Name (Error Case)

### Setup:
```
Existing classes: "User", "Team"
```

### Action:
```javascript
await updateClass(
  teamClassId,
  "User",  // Name already exists!
  "Team description",
  teamSchema
);
```

### Expected Results:
❌ Error returned: "A class with this name already exists in this version"
✅ No class updated
✅ No references updated
✅ Database constraint prevents duplicate

## Test Case 7: Multiple Versions Isolation

### Setup:
```
Version 1.0.0:
  - Class: User

Version 2.0.0:
  - Class: User
  - Class: Team (references User)
```

### Action:
```javascript
// Rename User in version 1.0.0 only
await updateClass(
  userClassIdV1,
  "Person",
  "A person",
  userSchema
);
```

### Expected Results:
✅ Version 1.0.0: User renamed to Person
✅ Version 2.0.0: User remains unchanged
✅ Version 2.0.0: Team still references `#/components/schemas/User`
✅ Versions are properly isolated

## Test Case 8: Mixed Property Types

### Setup:
```
Class: Company
  - id: string (regular property)
  - ceo: $ref(User) (reference property)
  - employees: array[$ref(User)] (array reference)
  - metadata: object (inline object, no reference)
```

### Action:
```javascript
await updateClass(
  userClassId,
  "Person",
  "A person",
  userSchema
);
```

### Expected Results:
✅ Company.id unchanged (regular property)
✅ Company.ceo updated to `$ref: #/components/schemas/Person`
✅ Company.employees updated to `$ref: #/components/schemas/Person`
✅ Company.metadata unchanged (not a reference)

## Performance Test

### Setup:
```
Version with:
- 50 classes
- 500 properties total
- 100 properties reference the target class
```

### Action:
```javascript
await updateClass(targetClassId, "NewName", "desc", schema);
```

### Expected Performance:
✅ Completes in < 2 seconds
✅ Only updated properties are written
✅ No unnecessary database queries

### Monitoring:
- Query count
- Execution time
- Database load

## Integration Test: Full Workflow

### Steps:
1. Create classes: User, Team, Project
2. Add references to User from Team and Project
3. Verify references work in OpenAPI spec
4. Rename User to Person
5. Reload canvas
6. Verify OpenAPI spec updated
7. Verify relationships shown correctly on canvas

### Expected:
✅ All steps complete successfully
✅ No broken references at any point
✅ Canvas shows correct relationships
✅ OpenAPI spec validates successfully

## Edge Cases

### Case: Empty version
- No classes exist
- Rename should work but update nothing

### Case: Property data is null
- Handle gracefully, skip that property

### Case: Malformed JSON in property data
- Parse error should not crash entire operation
- Skip malformed property, continue with others

### Case: Very long class name
- Database constraints should enforce limits
- Error returned before processing references

## Rollback Test

### Setup:
Simulate database error during reference update

### Expected:
✅ Transaction rolled back
✅ Class name not changed
✅ All references remain as before
✅ Error message returned to user

---

## Test Execution Checklist

- [ ] Test Case 1: Simple Rename
- [ ] Test Case 2: No Name Change
- [ ] Test Case 3: Class With No References
- [ ] Test Case 4: Self-Reference
- [ ] Test Case 5: Circular References
- [ ] Test Case 6: Duplicate Name (Error Case)
- [ ] Test Case 7: Multiple Versions Isolation
- [ ] Test Case 8: Mixed Property Types
- [ ] Performance Test
- [ ] Integration Test: Full Workflow
- [ ] All Edge Cases

## Success Criteria

✅ All test cases pass
✅ No data loss
✅ No broken references
✅ Performance acceptable
✅ Error handling correct
✅ Transaction safety maintained

